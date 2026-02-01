from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.core.llm_router import LLMResponse, LLMUnavailableError, llm_router
from app.core.report_safety import FORBIDDEN_WORDS, report_safety
from app.db.models import Order, OrderStatus, Report, ReportModel, Tariff
from app.db.session import get_session


SYSTEM_PROMPT = """
Ты — аналитический ассистент. Подготовь структурированный отчёт на русском языке.
Соблюдай нейтральную лексику и используй только допустимые формулировки:
«личные предрасположенности», «навыки и компетенции», «интересы и мотивация»,
«жизненный и профессиональный опыт», «поведенческие паттерны», «ценности»,
«рабочие гипотезы», «варианты сценариев», «зоны роста».
Запрещено использовать слова: «нумерология», «предназначение», «судьба», «карма», «прогноз».
Запрещены обещания результата, гарантии, проценты, «100%». Не давай медицинских, финансовых,
правовых или иных советов из красных зон.
В конце добавь дисклеймеры:
- «Сервис не является консультацией, прогнозом или рекомендацией к действию»
- «Все выводы носят аналитический и описательный характер»
- «Ответственность за решения остаётся за пользователем»
- «Сервис не гарантирует финансовых или иных результатов»
""".strip()


class ReportService:
    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)
        forbidden_terms = [*FORBIDDEN_WORDS, "натальный", "натальные", "натальной", "натальных"]
        self._facts_forbidden_regexes = [
            re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
            for term in forbidden_terms
        ]

    async def generate_report(self, *, user_id: int, state: dict[str, Any]) -> LLMResponse | None:
        facts_pack = self._build_facts_pack(user_id=user_id, state=state)
        prompt = SYSTEM_PROMPT
        attempts = 0
        safety_history: list[dict[str, Any]] = []
        last_response: LLMResponse | None = None

        while True:
            try:
                response = await asyncio.to_thread(llm_router.generate, facts_pack, prompt)
            except LLMUnavailableError:
                self._logger.warning("llm_unavailable", extra={"user_id": user_id})
                return None

            evaluation = report_safety.evaluate(response.text)
            safety_history.append(report_safety.evaluation_payload(evaluation))
            last_response = response

            if evaluation.is_safe:
                break

            if attempts >= 2:
                break

            attempts += 1
            prompt = report_safety.build_retry_prompt(SYSTEM_PROMPT, evaluation)

        if last_response and evaluation.is_safe:
            safety_flags = report_safety.build_flags(
                attempts=attempts,
                history=safety_history,
                provider=last_response.provider,
                model=last_response.model,
            )
            self._persist_report(
                user_id=user_id,
                state=state,
                response=last_response,
                safety_flags=safety_flags,
            )
            return last_response

        if last_response:
            safety_flags = report_safety.build_flags(
                attempts=attempts,
                history=safety_history,
                provider=last_response.provider,
                model=last_response.model,
            )
            self._persist_report(
                user_id=user_id,
                state=state,
                response=last_response,
                safety_flags=safety_flags,
                force_store=True,
            )
        return None

    def _persist_report(
        self,
        *,
        user_id: int,
        state: dict[str, Any],
        response: LLMResponse,
        safety_flags: dict[str, Any],
        force_store: bool = False,
    ) -> None:
        tariff_value = state.get("selected_tariff")
        if not tariff_value:
            self._logger.warning("report_tariff_missing", extra={"user_id": user_id})
            return
        try:
            tariff = Tariff(tariff_value)
        except ValueError:
            self._logger.warning(
                "report_tariff_invalid",
                extra={"user_id": user_id, "tariff": tariff_value},
            )
            return

        order_id = None
        paid_tariffs = {Tariff.T1, Tariff.T2, Tariff.T3}
        with get_session() as session:
            if tariff in paid_tariffs:
                order_id = self._resolve_paid_order_id(session, state, user_id)
                if not order_id and not force_store:
                    return
            report = Report(
                user_id=user_id,
                order_id=order_id,
                tariff=tariff,
                report_text=response.text,
                model_used=self._map_model(response.provider),
                safety_flags=safety_flags,
            )
            session.add(report)

    def _resolve_paid_order_id(self, session, state: dict[str, Any], user_id: int) -> int | None:
        order_id = state.get("order_id")
        if not order_id:
            self._logger.warning("report_order_missing", extra={"user_id": user_id})
            return None
        order = session.get(Order, int(order_id))
        if not order or order.status != OrderStatus.PAID:
            self._logger.warning(
                "report_order_not_paid",
                extra={"user_id": user_id, "order_id": order_id},
            )
            return None
        return order.id

    @staticmethod
    def _map_model(provider: str) -> ReportModel | None:
        if provider == "gemini":
            return ReportModel.GEMINI
        if provider == "openai":
            return ReportModel.CHATGPT
        return None

    def _build_facts_pack(self, *, user_id: int, state: dict[str, Any]) -> dict[str, Any]:
        profile = state.get("profile") or {}
        questionnaire = state.get("questionnaire") or {}
        facts_pack = {
            "user_id": user_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tariff": state.get("selected_tariff"),
            "profile": {
                "name": profile.get("name"),
                "birth_date": profile.get("birth_date"),
                "birth_time": profile.get("birth_time"),
                "birth_place": {
                    "city": (profile.get("birth_place") or {}).get("city"),
                    "region": (profile.get("birth_place") or {}).get("region"),
                    "country": (profile.get("birth_place") or {}).get("country"),
                },
            },
            "questionnaire": {
                "version": questionnaire.get("version"),
                "status": questionnaire.get("status"),
                "answers": questionnaire.get("answers") or {},
            },
        }
        return self._sanitize_facts_pack(facts_pack)

    def _sanitize_facts_pack(self, payload: Any) -> Any:
        if payload is None:
            return None
        if isinstance(payload, str):
            return self._sanitize_text(payload)
        if isinstance(payload, dict):
            return {key: self._sanitize_facts_pack(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self._sanitize_facts_pack(value) for value in payload]
        return payload

    def _sanitize_text(self, text: str) -> str:
        sanitized = text
        for regex in self._facts_forbidden_regexes:
            sanitized = regex.sub("удалено", sanitized)
        sanitized = re.sub(r"\s{2,}", " ", sanitized).strip()
        return sanitized

report_service = ReportService()
