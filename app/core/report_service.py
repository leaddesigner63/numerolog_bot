from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from app.core.llm_router import LLMResponse, LLMUnavailableError, llm_router
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

    async def generate_report(self, *, user_id: int, state: dict[str, Any]) -> LLMResponse | None:
        facts_pack = {
            "user_id": user_id,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "tariff": state.get("selected_tariff"),
            "profile": state.get("profile"),
            "questionnaire": state.get("questionnaire"),
        }

        try:
            response = await asyncio.to_thread(llm_router.generate, facts_pack, SYSTEM_PROMPT)
        except LLMUnavailableError:
            self._logger.warning("llm_unavailable", extra={"user_id": user_id})
            return None
        self._persist_report(user_id=user_id, state=state, response=response)
        return response

    def _persist_report(self, *, user_id: int, state: dict[str, Any], response: LLMResponse) -> None:
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
            report = Report(
                user_id=user_id,
                order_id=order_id,
                tariff=tariff,
                report_text=response.text,
                model_used=self._map_model(response.provider),
                safety_flags=self._build_safety_flags(response),
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

    @staticmethod
    def _build_safety_flags(response: LLMResponse) -> dict[str, Any]:
        return {
            "provider": response.provider,
            "model": response.model,
            "filtered": False,
        }


report_service = ReportService()
