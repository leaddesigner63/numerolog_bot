from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.llm_router import LLMResponse, LLMUnavailableError, llm_router
from app.core.prompt_settings import resolve_tariff_prompt
from app.core.report_safety import report_safety
from app.db.models import (
    Order,
    OrderFulfillmentStatus,
    OrderStatus,
    QuestionnaireResponse,
    QuestionnaireStatus,
    Report,
    ReportJob,
    ReportJobStatus,
    ReportModel,
    ScreenStateRecord,
    Tariff,
    User,
    UserProfile,
)
from app.db.session import get_session
from sqlalchemy import select


REPORT_FRAMEWORK_TEMPLATE = """
Единый каркас отчёта (используй разделы строго по тарифу):
- T0: витрина структуры, краткое резюме (5–7 пунктов), сильные стороны, зоны роста, ориентиры по сферам, короткая нейтральная ретроспектива (2–3 предложения), дисклеймеры.
- T1: полный краткий отчёт с теми же секциями, но без сокращений.
- T2: всё из T1 + блок «Фокус на деньги» (2–4 сценария с логикой, навыками, форматом дохода без обещаний, рисками, способом проверки за 2–4 недели).
- T3: всё из T2 + план действий (1 месяц по неделям, 1 год по месяцам) + блок «Энергия/отношения» без медицины.
""".strip()

PAID_TARIFFS = {Tariff.T1, Tariff.T2, Tariff.T3}


class ReportService:
    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

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

            if not settings.report_safety_enabled:
                safety_flags = report_safety.build_flags(
                    attempts=0,
                    history=[],
                    provider=response.provider,
                    model=response.model,
                )
                safety_flags["filtering_disabled"] = True
                self._persist_report(
                    user_id=user_id,
                    state=state,
                    response=response,
                    safety_flags=safety_flags,
                )
                return response

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

    async def generate_report_by_job(self, *, job_id: int) -> Report | None:
        user_id: int | None = None
        state_data: dict[str, Any] = {}
        with get_session() as session:
            job = session.get(ReportJob, job_id)
            if not job:
                self._logger.warning("report_job_missing", extra={"job_id": job_id})
                return None
            if job.order_id:
                existing_report = (
                    session.execute(
                        select(Report).where(Report.order_id == job.order_id).limit(1)
                    )
                    .scalars()
                    .first()
                )
                if existing_report:
                    job.status = ReportJobStatus.COMPLETED
                    job.last_error = None
                    session.add(job)
                    session.expunge(existing_report)
                    return existing_report
            user = session.get(User, job.user_id)
            if not user:
                job.status = ReportJobStatus.FAILED
                job.last_error = "user_missing"
                session.add(job)
                return None
            user_id = user.id
            telegram_user_id = user.telegram_user_id
            profile = session.execute(
                select(UserProfile).where(UserProfile.user_id == user.id).limit(1)
            ).scalar_one_or_none()
            if not profile:
                job.status = ReportJobStatus.FAILED
                job.last_error = "profile_missing"
                session.add(job)
                return None
            if job.tariff in {Tariff.T2, Tariff.T3}:
                latest_questionnaire = (
                    session.execute(
                        select(QuestionnaireResponse)
                        .where(QuestionnaireResponse.user_id == user.id)
                        .order_by(QuestionnaireResponse.updated_at.desc(), QuestionnaireResponse.id.desc())
                        .limit(1)
                    )
                    .scalars()
                    .first()
                )
                if (
                    not latest_questionnaire
                    or latest_questionnaire.status != QuestionnaireStatus.COMPLETED
                ):
                    job.status = ReportJobStatus.FAILED
                    job.last_error = "questionnaire_incomplete"
                    session.add(job)
                    return None
            if job.tariff in PAID_TARIFFS:
                order = session.get(Order, job.order_id) if job.order_id else None
                expected_amount = settings.tariff_prices_rub.get(job.tariff.value)
                if not order or order.status != OrderStatus.PAID:
                    job.status = ReportJobStatus.FAILED
                    job.last_error = "paid_order_missing"
                    session.add(job)
                    return None
                if expected_amount is not None and float(order.amount or 0) != float(expected_amount):
                    job.status = ReportJobStatus.FAILED
                    job.last_error = "paid_order_amount_mismatch"
                    session.add(job)
                    return None
            state_record = session.get(ScreenStateRecord, telegram_user_id)
            state_data = dict(state_record.data or {}) if state_record else {}
            state_data["selected_tariff"] = job.tariff.value
            if job.order_id is not None:
                state_data["order_id"] = str(job.order_id)
            else:
                state_data.pop("order_id", None)
            if not state_data:
                job.status = ReportJobStatus.FAILED
                job.last_error = "state_missing"
                session.add(job)
                return None
            job.status = ReportJobStatus.IN_PROGRESS
            job.attempts = (job.attempts or 0) + 1
            job.last_error = None
            session.add(job)
            session.flush()

        try:
            if user_id is None:
                raise RuntimeError("report_job_user_id_missing")
            response = await self.generate_report(user_id=user_id, state=state_data)
        except Exception as exc:
            with get_session() as session:
                job = session.get(ReportJob, job_id)
                if job:
                    job.status = ReportJobStatus.FAILED
                    job.last_error = str(exc)
                    session.add(job)
            return None

        if not response:
            with get_session() as session:
                job = session.get(ReportJob, job_id)
                if job:
                    job.status = ReportJobStatus.FAILED
                    job.last_error = "report_generation_failed"
                    session.add(job)
            return None

        with get_session() as session:
            job = session.get(ReportJob, job_id)
            if not job:
                return None
            report = None
            should_lookup_by_order = job.order_id is not None and job.tariff in PAID_TARIFFS
            if should_lookup_by_order:
                report = (
                    session.execute(
                        select(Report).where(Report.order_id == job.order_id).limit(1)
                    )
                    .scalars()
                    .first()
                )
                if not report:
                    job.status = ReportJobStatus.FAILED
                    job.last_error = "report_not_saved_for_order"
                    session.add(job)
                    return None
            else:
                report = (
                    session.execute(
                        select(Report)
                        .where(
                            Report.user_id == job.user_id,
                            Report.tariff == job.tariff,
                        )
                        .order_by(Report.created_at.desc())
                        .limit(1)
                    )
                    .scalars()
                    .first()
                )
                if not report:
                    job.status = ReportJobStatus.FAILED
                    job.last_error = "report_not_saved"
                    session.add(job)
                    return None
            job.status = ReportJobStatus.COMPLETED
            job.last_error = None
            session.add(job)
            session.expunge(report)
            return report

    def _build_system_prompt(self, state: dict[str, Any]) -> str:
        tariff_value = state.get("selected_tariff")
        tariff_label = None
        if tariff_value:
            try:
                tariff_label = Tariff(tariff_value)
            except ValueError:
                tariff_label = None
        tariff_label = tariff_label or Tariff.T1
        base_prompt = resolve_tariff_prompt(tariff_label)
        return (
            f"{base_prompt}\n\n"
            f"Текущий тариф: {tariff_label.value}.\n"
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
        with get_session() as session:
            if tariff in PAID_TARIFFS:
                order_id = self._resolve_paid_order_id(session, state, user_id)
                if not order_id and not force_store:
                    self._logger.warning(
                        "paid_order_missing",
                        extra={"user_id": user_id, "tariff": tariff.value},
                    )
                    return
                if order_id and self._order_has_report(session, order_id):
                    self._logger.info(
                        "report_already_exists_for_order",
                        extra={"user_id": user_id, "order_id": order_id},
                    )
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
            session.flush()
            if order_id:
                order = session.get(Order, order_id)
                if order:
                    order.fulfillment_status = OrderFulfillmentStatus.COMPLETED
                    order.fulfilled_at = datetime.now(timezone.utc)
                    order.fulfilled_report_id = report.id
                    session.add(order)

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
    def _order_has_report(session, order_id: int) -> bool:
        return (
            session.execute(select(Report.id).where(Report.order_id == order_id).limit(1))
            .scalars()
            .first()
            is not None
        )

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
                "gender": profile.get("gender"),
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
        return facts_pack

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
                "## 1 месяц (по неделям)\n"
                "- Неделя 1: уточнить фокус, выбрать одну цель и критерий результата.\n"
                "- Неделя 2: собрать план задач и ограничить параллельные инициативы.\n"
                "- Неделя 3: выполнить ключевые шаги и зафиксировать метрики.\n"
                "- Неделя 4: оценить результаты, скорректировать план.\n\n"
                "## 1 год (по месяцам)\n"
                "- 1–3 месяцы: укрепить базовые навыки и рабочие процессы.\n"
                "- 4–6 месяцы: расширить задачи и закрепить ритм.\n"
                "- 7–9 месяцы: повысить самостоятельность и качество результата.\n"
                "- 10–12 месяцы: стабилизировать подход и выбрать следующий фокус.\n\n"
                "## Энергия и отношения\n"
                "- Вопросы к себе: что поддерживает устойчивость, где нужны границы и отдых."
            )

        return "\n\n".join(sections)


report_service = ReportService()
