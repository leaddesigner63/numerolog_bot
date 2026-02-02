from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.bot.questionnaire.config import load_questionnaire_config
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

REPORT_FRAMEWORK_TEMPLATE = """
Единый каркас отчёта (используй разделы строго по тарифу):
- T0: витрина структуры, краткое резюме (5–7 пунктов), сильные стороны, зоны роста, ориентиры по сферам, короткая нейтральная ретроспектива (2–3 предложения), дисклеймеры.
- T1: полный краткий отчёт с теми же секциями, но без сокращений.
- T2: всё из T1 + блок «Фокус на деньги» (2–4 сценария с логикой, навыками, форматом дохода без обещаний, рисками, способом проверки за 2–4 недели).
- T3: всё из T2 + план действий (1 месяц по неделям, 1 год по месяцам) + блок «Энергия/отношения» без медицины.
""".strip()


class ReportService:
    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)
        forbidden_terms = sorted(set(FORBIDDEN_WORDS))
        self._facts_forbidden_regexes = [
            re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
            for term in forbidden_terms
        ]

    async def generate_report(self, *, user_id: int, state: dict[str, Any]) -> LLMResponse | None:
        facts_pack = self._build_facts_pack(user_id=user_id, state=state)
        base_prompt = self._build_system_prompt(state)
        prompt = base_prompt
        attempts = 0
        safety_history: list[dict[str, Any]] = []
        last_response: LLMResponse | None = None
        evaluation = None

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
            prompt = report_safety.build_retry_prompt(base_prompt, evaluation)

        if last_response and evaluation and evaluation.is_safe:
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

        if last_response and evaluation:
            if evaluation.red_zones:
                safety_flags = report_safety.build_flags(
                    attempts=attempts,
                    history=safety_history,
                    provider=last_response.provider,
                    model=last_response.model,
                    safe_refusal=True,
                )
                safe_response = LLMResponse(
                    text=report_safety.build_safe_refusal(),
                    provider="safety_filter",
                    model="safe_refusal",
                )
                self._persist_report(
                    user_id=user_id,
                    state=state,
                    response=safe_response,
                    safety_flags=safety_flags,
                    force_store=True,
                )
                return safe_response
            self._logger.info(
                "report_safety_fallback",
                extra={"user_id": user_id, "attempts": attempts},
            )
            safety_flags = report_safety.build_flags(
                attempts=attempts,
                history=safety_history,
                provider=last_response.provider,
                model=last_response.model,
            )
            safety_flags["fallback_report"] = True
            fallback_response = LLMResponse(
                text=self._build_fallback_report(state),
                provider="safety_fallback",
                model="template",
            )
            self._persist_report(
                user_id=user_id,
                state=state,
                response=fallback_response,
                safety_flags=safety_flags,
                force_store=True,
            )
            return fallback_response
        return None

    def _build_system_prompt(self, state: dict[str, Any]) -> str:
        tariff_value = state.get("selected_tariff")
        tariff_label = None
        if tariff_value:
            try:
                tariff_label = Tariff(tariff_value).value
            except ValueError:
                tariff_label = None
        tariff_label = tariff_label or Tariff.T1.value
        return (
            f"{SYSTEM_PROMPT}\n\n"
            f"Текущий тариф: {tariff_label}.\n"
            f"{REPORT_FRAMEWORK_TEMPLATE}\n"
            "Сформируй отчёт только для указанного тарифа, "
            "используй чёткие заголовки и списки."
        )

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
        normalized_profile = self._normalize_profile(profile)
        normalized_questionnaire = self._normalize_questionnaire(questionnaire)
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
            "normalized": {
                "profile": normalized_profile,
                "questionnaire": normalized_questionnaire,
            },
        }
        return self._sanitize_facts_pack(facts_pack)

    def _build_fallback_report(self, state: dict[str, Any]) -> str:
        tariff_value = state.get("selected_tariff")
        try:
            tariff = Tariff(tariff_value) if tariff_value else Tariff.T1
        except ValueError:
            tariff = Tariff.T1

        header = "Резервный аналитический отчёт (без персонализации)."
        base_sections = [
            "Как читать отчёт:\n"
            "- Текст носит аналитический и описательный характер.\n"
            "- Используйте выводы как рабочие гипотезы и ориентиры.",
            "Резюме:\n"
            "• Отмечается потенциал в сочетании практичности и гибкости.\n"
            "• В фокусе — личные предрасположенности, интересы и мотивация.\n"
            "• Сильные стороны проявляются через навыки и компетенции.\n"
            "• Зоны роста связаны с уточнением приоритетов и системностью.\n"
            "• Эффективность повышается при опоре на опыт и осознанные цели.",
            "Сильные стороны:\n"
            "• Способность к анализу и структурированию.\n"
            "• Внимание к деталям и устойчивость к нагрузкам.\n"
            "• Открытость к новым задачам при понятных правилах.",
            "Зоны потенциального роста:\n"
            "• Баланс между скоростью и качеством.\n"
            "• Развитие коммуникации и обратной связи.\n"
            "• Планирование ресурсов и темпа.",
            "Ориентиры по сферам:\n"
            "• Работа и развитие: выбирать задачи с измеримым результатом.\n"
            "• Обучение: укреплять базовые навыки и прикладные инструменты.\n"
            "• Личная динамика: поддерживать устойчивый режим и фокус.",
        ]

        if tariff == Tariff.T0:
            sections = [
                header,
                "Витрина структуры полного отчёта:\n"
                "• Резюме\n"
                "• Сильные стороны\n"
                "• Зоны потенциального роста\n"
                "• Ориентиры по сферам\n"
                "• Нейтральная ретроспектива",
                "Краткое резюме:\n"
                "• Отмечается сочетание практичности и гибкости.\n"
                "• Важна опора на навыки и компетенции.\n"
                "• Рост поддерживается через ясные цели.",
                "Сильные стороны:\n"
                "• Аналитический подход и структурирование.\n"
                "• Устойчивость к изменениям.",
                "Зоны потенциального роста:\n"
                "• Фокус на приоритетах и темпе.",
                "Ориентиры по сферам:\n"
                "• Развитие через практику и обратную связь.",
                "Нейтральная ретроспектива:\n"
                "Возможно, вы уже проходили этап уточнения целей и формата развития.",
            ]
        else:
            sections = [header, *base_sections]

        if tariff in {Tariff.T2, Tariff.T3}:
            sections.append(
                "Фокус на деньги — сценарии:\n"
                "1) Сценарий A: развитие прикладных компетенций.\n"
                "   Почему логично: опирается на опыт и повторяемые сильные стороны.\n"
                "   Навыки: аналитика, коммуникация, организация процессов.\n"
                "   Формат дохода: проектная работа или фиксированные задачи.\n"
                "   Риски и ограничения: распыление внимания, перегрузка задачами.\n"
                "   Проверка за 2–4 недели: один пилотный проект с метриками результата.\n"
                "2) Сценарий B: усиление экспертизы в выбранной нише.\n"
                "   Почему логично: повышает ценность за счёт глубины.\n"
                "   Навыки: изучение рынка, упаковка опыта, самоорганизация.\n"
                "   Формат дохода: экспертные сессии или продуктовые задачи.\n"
                "   Риски и ограничения: длительный цикл окупаемости.\n"
                "   Проверка за 2–4 недели: тестовый запуск предложения и сбор обратной связи."
            )

        if tariff == Tariff.T3:
            sections.append(
                "План действий:\n"
                "1 месяц (по неделям):\n"
                "- Неделя 1: уточнить фокус, выбрать одну цель и критерий результата.\n"
                "- Неделя 2: собрать план задач и ограничить параллельные инициативы.\n"
                "- Неделя 3: выполнить ключевые шаги и зафиксировать метрики.\n"
                "- Неделя 4: оценить результаты, скорректировать план.\n\n"
                "1 год (помесячно):\n"
                "- 1–3 месяцы: укрепить базовые навыки и рабочие процессы.\n"
                "- 4–6 месяцы: расширить задачи и закрепить ритм.\n"
                "- 7–9 месяцы: повысить самостоятельность и качество результата.\n"
                "- 10–12 месяцы: стабилизировать подход и выбрать следующий фокус.\n"
                "Энергия и отношения:\n"
                "- Вопросы к себе: что поддерживает устойчивость, где нужны границы и отдых."
            )

        return "\n\n".join(sections)

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

    @staticmethod
    def _normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
        birth_place = profile.get("birth_place") or {}
        return {
            "name": (profile.get("name") or "").strip() or None,
            "birth_date": profile.get("birth_date"),
            "birth_time": profile.get("birth_time"),
            "birth_place_city": (birth_place.get("city") or "").strip() or None,
            "birth_place_region": (birth_place.get("region") or "").strip() or None,
            "birth_place_country": (birth_place.get("country") or "").strip() or None,
        }

    def _normalize_questionnaire(self, questionnaire: dict[str, Any]) -> dict[str, Any]:
        answers = questionnaire.get("answers") or {}
        config = load_questionnaire_config()
        normalized_answers: list[dict[str, Any]] = []
        for question_id, question in config.questions.items():
            if question_id not in answers:
                continue
            raw_answer = answers.get(question_id)
            answer_label = None
            if question.question_type == "choice":
                answer_label = next(
                    (
                        option.get("label")
                        for option in question.options
                        if str(option.get("value")) == str(raw_answer)
                    ),
                    None,
                )
            elif question.question_type == "scale":
                labels = (question.scale or {}).get("labels") or {}
                answer_label = labels.get(str(raw_answer))
            normalized_answers.append(
                {
                    "id": question_id,
                    "type": question.question_type,
                    "required": question.required,
                    "question": question.text,
                    "answer": raw_answer,
                    "answer_label": answer_label,
                }
            )
        return {
            "version": questionnaire.get("version") or config.version,
            "status": questionnaire.get("status"),
            "answers": normalized_answers,
            "answers_count": len(normalized_answers),
        }

report_service = ReportService()
