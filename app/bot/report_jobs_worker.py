from __future__ import annotations

import asyncio
from collections import Counter
import logging
import os
import random
import socket
import uuid
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy import select, update

from app.bot.handlers import screens as screens_handler
from app.bot.handlers.screen_manager import screen_manager
from app.core.config import settings
from app.core.report_service import report_service
from app.db.models import (
    Order,
    OrderStatus,
    ReportJob,
    ReportJobStatus,
    ScreenStateRecord,
    ServiceHeartbeat,
    User,
)
from app.db.session import get_session
from app.services.marketing_messaging import send_marketing_message


class ReportJobWorker:

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)
        self._service_name = "report_jobs_worker"
        self._host = socket.gethostname()
        self._pid = os.getpid()
        self._skip_reasons_counter: Counter[str] = Counter()
        self._retry_base_seconds = 60
        self._retry_max_seconds = 60 * 60

    async def run(self, bot: Bot) -> None:
        poll_interval = max(settings.report_job_poll_interval_seconds, 1)
        while True:
            try:
                await self._process_pending_jobs(bot)
                await self._process_stalled_users(bot)
                await self._process_checkout_value_nudges(bot)
            except Exception as exc:
                self._logger.warning(
                    "report_job_worker_failed",
                    extra={"error": str(exc)},
                    exc_info=True,
                )
            await asyncio.sleep(poll_interval)

    async def _process_pending_jobs(self, bot: Bot) -> None:
        self._update_heartbeat()
        job_ids = []
        with get_session() as session:
            job_ids = (
                session.execute(
                    select(ReportJob.id)
                    .where(
                        ReportJob.status.in_(
                            [ReportJobStatus.PENDING, ReportJobStatus.IN_PROGRESS]
                        )
                    )
                    .order_by(ReportJob.created_at.asc())
                )
                .scalars()
                .all()
            )
        for job_id in job_ids:
            claimed = self._claim_job(job_id)
            if not claimed:
                continue
            await self._handle_job(bot, job_id)

    async def _process_stalled_users(self, bot: Bot) -> None:
        threshold_hours = int(getattr(settings, "resume_nudge_delay_hours", 6) or 6)
        threshold = timedelta(hours=max(threshold_hours, 1))
        now = datetime.now(timezone.utc)

        with get_session() as session:
            state_rows = session.execute(select(ScreenStateRecord)).scalars().all()
            for state_row in state_rows:
                state_data: dict | None = None
                try:
                    state_data = self._get_state_data_or_none(
                        state_row=state_row,
                        flow_name="resume_nudge",
                    )
                    if state_data is None:
                        continue
                    if self._should_skip_by_retry(
                        state_data=state_data,
                        key_prefix="resume_nudge",
                        now=now,
                    ):
                        continue
                    critical_at = self._parse_dt(state_data.get("last_critical_step_at"))
                    if not critical_at:
                        continue
                    if now - critical_at < threshold:
                        continue
                    if state_data.get("resume_nudge_sent_at"):
                        continue

                    user = session.execute(
                        select(User).where(User.telegram_user_id == state_row.telegram_user_id)
                    ).scalar_one_or_none()
                    if user is None:
                        continue

                    if self._has_paid_order(session, user.id):
                        continue

                    deep_link = self._build_resume_deeplink(state_data=state_data)
                    message_text = (
                        "Вы остановились на важном шаге.\n"
                        "Если хотите, можно мягко продолжить с того же места 👇\n"
                        f"{deep_link}"
                    )
                    resume_campaign = str(getattr(settings, "resume_nudge_campaign", "resume_after_stall_v1") or "resume_after_stall_v1")
                    send_result = await send_marketing_message(
                        bot=bot,
                        session=session,
                        user_id=user.id,
                        campaign=resume_campaign,
                        message_text=message_text,
                    )
                    if not send_result.sent:
                        self._logger.info(
                            "resume_nudge_send_skipped",
                            extra={
                                "campaign": resume_campaign,
                                "user_id": user.id,
                                "telegram_user_id": state_row.telegram_user_id,
                                "reason": send_result.reason,
                            },
                        )
                        continue

                    sent_at = now.isoformat()
                    state_data["resume_nudge_sent_at"] = sent_at
                    state_data["resume_nudge_campaign"] = resume_campaign
                    state_data["resume_nudge_target_screen_id"] = state_data.get("last_critical_screen_id")
                    state_data = self._clear_processing_errors(
                        state_data=state_data,
                        key_prefix="resume_nudge",
                    )
                    state_row.data = state_data
                    session.add(state_row)
                    screen_manager.record_transition_event_safe(
                        user_id=state_row.telegram_user_id,
                        from_screen=state_data.get("last_critical_screen_id"),
                        to_screen=state_data.get("last_critical_screen_id") or "UNKNOWN",
                        trigger_type="system",
                        trigger_value="resume_nudge:sent",
                        transition_status="success",
                        metadata_json={
                            "campaign": resume_campaign,
                            "reason": "resume_nudge_sent",
                            "tariff": state_data.get("selected_tariff"),
                        },
                    )
                except Exception as exc:
                    state_data = self._register_processing_error(
                        state_data=state_data if isinstance(state_data, dict) else {},
                        key_prefix="resume_nudge",
                        now=now,
                    )
                    state_row.data = state_data
                    session.add(state_row)
                    self._logger.warning(
                        "resume_nudge_process_failed",
                        extra={"telegram_user_id": state_row.telegram_user_id, "error": str(exc)},
                        exc_info=True,
                    )

    async def _process_checkout_value_nudges(self, bot: Bot) -> None:
        now = datetime.now(timezone.utc)
        target_screens = {"S2", "S4"}
        min_delay_minutes = max(
            int(getattr(settings, "checkout_value_nudge_min_delay_minutes", 10) or 10),
            1,
        )
        max_delay_minutes = max(
            int(getattr(settings, "checkout_value_nudge_max_delay_minutes", 30) or 30),
            min_delay_minutes,
        )
        campaign = str(
            getattr(settings, "checkout_value_nudge_campaign", "checkout_value_nudge_v1")
            or "checkout_value_nudge_v1"
        )

        with get_session() as session:
            state_rows = session.execute(select(ScreenStateRecord)).scalars().all()
            for state_row in state_rows:
                state_data: dict | None = None
                try:
                    state_data = self._get_state_data_or_none(
                        state_row=state_row,
                        flow_name="checkout_value_nudge",
                    )
                    if state_data is None:
                        continue
                    if self._should_skip_by_retry(
                        state_data=state_data,
                        key_prefix="checkout_value_nudge",
                        now=now,
                    ):
                        continue
                    if state_data.get("checkout_value_nudge_sent_at"):
                        continue

                    if state_row.screen_id in target_screens and not state_data.get("checkout_value_nudge_first_seen_at"):
                        delay_minutes = random.randint(min_delay_minutes, max_delay_minutes)
                        due_at = now + timedelta(minutes=delay_minutes)
                        state_data["checkout_value_nudge_first_seen_at"] = now.isoformat()
                        state_data["checkout_value_nudge_due_at"] = due_at.isoformat()
                        state_data["checkout_value_nudge_target_screen_id"] = state_row.screen_id
                        state_data["checkout_value_nudge_delay_minutes"] = delay_minutes
                        state_row.data = state_data
                        session.add(state_row)

                    due_at = self._parse_dt(state_data.get("checkout_value_nudge_due_at"))
                    if not due_at or now < due_at:
                        continue

                    user = session.execute(
                        select(User).where(User.telegram_user_id == state_row.telegram_user_id)
                    ).scalar_one_or_none()
                    if user is None:
                        continue
                    if self._has_paid_order(session, user.id):
                        continue

                    deep_link = self._build_resume_deeplink(state_data=state_data)
                    message_text = (
                        "Ваш персональный разбор уже почти готов — после оплаты откроется вся практическая ценность и рекомендации.\n"
                        f"{deep_link}"
                    )
                    send_result = await send_marketing_message(
                        bot=bot,
                        session=session,
                        user_id=user.id,
                        campaign=campaign,
                        message_text=message_text,
                    )
                    if not send_result.sent:
                        self._logger.info(
                            "checkout_value_nudge_send_skipped",
                            extra={
                                "campaign": campaign,
                                "user_id": user.id,
                                "telegram_user_id": state_row.telegram_user_id,
                                "reason": send_result.reason,
                            },
                        )
                        continue

                    sent_at = now.isoformat()
                    state_data["checkout_value_nudge_sent_at"] = sent_at
                    state_data["checkout_value_nudge_campaign"] = campaign
                    state_data = self._clear_processing_errors(
                        state_data=state_data,
                        key_prefix="checkout_value_nudge",
                    )
                    state_row.data = state_data
                    session.add(state_row)
                    screen_manager.record_transition_event_safe(
                        user_id=state_row.telegram_user_id,
                        from_screen=state_data.get("checkout_value_nudge_target_screen_id"),
                        to_screen=state_data.get("checkout_value_nudge_target_screen_id") or "UNKNOWN",
                        trigger_type="system",
                        trigger_value="checkout_value_nudge:sent",
                        transition_status="success",
                        metadata_json={
                            "campaign": campaign,
                            "reason": "checkout_value_nudge_sent",
                            "tariff": state_data.get("selected_tariff"),
                            "delay_minutes": state_data.get("checkout_value_nudge_delay_minutes"),
                        },
                    )
                except Exception as exc:
                    state_data = self._register_processing_error(
                        state_data=state_data if isinstance(state_data, dict) else {},
                        key_prefix="checkout_value_nudge",
                        now=now,
                    )
                    state_row.data = state_data
                    session.add(state_row)
                    self._logger.warning(
                        "checkout_value_nudge_process_failed",
                        extra={"telegram_user_id": state_row.telegram_user_id, "error": str(exc)},
                        exc_info=True,
                    )

    def _build_resume_deeplink(self, *, state_data: dict) -> str:
        bot_username = str(getattr(settings, "telegram_bot_username", "") or "").strip().lstrip("@")
        order_id = state_data.get("order_id")
        payload = "resume_nudge"
        if order_id:
            payload = f"resume_nudge_{order_id}"
        if bot_username:
            return f"https://t.me/{bot_username}?start={payload}"
        return f"/start {payload}"

    def _should_skip_by_retry(self, *, state_data: dict, key_prefix: str, now: datetime) -> bool:
        next_retry_at = self._parse_dt(state_data.get(f"{key_prefix}_next_retry_at"))
        if not next_retry_at:
            return False
        return now < next_retry_at

    def _register_processing_error(
        self,
        *,
        state_data: dict,
        key_prefix: str,
        now: datetime,
    ) -> dict:
        next_data = dict(state_data)
        current_count = int(next_data.get(f"{key_prefix}_error_count") or 0)
        next_count = current_count + 1
        retry_seconds = min(
            self._retry_base_seconds * (2 ** (next_count - 1)),
            self._retry_max_seconds,
        )
        next_data[f"{key_prefix}_last_error_at"] = now.isoformat()
        next_data[f"{key_prefix}_error_count"] = next_count
        next_data[f"{key_prefix}_next_retry_at"] = (now + timedelta(seconds=retry_seconds)).isoformat()
        return next_data

    @staticmethod
    def _clear_processing_errors(*, state_data: dict, key_prefix: str) -> dict:
        next_data = dict(state_data)
        next_data.pop(f"{key_prefix}_last_error_at", None)
        next_data.pop(f"{key_prefix}_error_count", None)
        next_data.pop(f"{key_prefix}_next_retry_at", None)
        return next_data

    @staticmethod
    def _parse_dt(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _has_paid_order(session, user_id: int) -> bool:
        paid_order = session.execute(
            select(Order.id).where(
                Order.user_id == user_id,
                Order.status == OrderStatus.PAID,
            )
        ).scalar_one_or_none()
        return paid_order is not None

    def _get_state_data_or_none(
        self,
        *,
        state_row: ScreenStateRecord,
        flow_name: str,
    ) -> dict | None:
        if isinstance(state_row.data, dict):
            return state_row.data.copy()

        reason = "invalid_state_data_type"
        self._skip_reasons_counter[reason] += 1
        state_data_type = type(state_row.data).__name__
        self._logger.warning(
            "nudge_state_skipped",
            extra={
                "telegram_user_id": state_row.telegram_user_id,
                "screen_id": state_row.screen_id,
                "flow": flow_name,
                "reason": reason,
                "state_data_type": state_data_type,
                "skip_reason_count": self._skip_reasons_counter[reason],
            },
        )
        screen_manager.record_transition_event_safe(
            user_id=state_row.telegram_user_id,
            from_screen=state_row.screen_id,
            to_screen=state_row.screen_id or "UNKNOWN",
            trigger_type="system",
            trigger_value=f"{flow_name}:skipped",
            transition_status="skipped",
            metadata_json={
                "reason": reason,
                "state_data_type": state_data_type,
                "skip_reason_count": self._skip_reasons_counter[reason],
            },
        )
        return None

    def _update_heartbeat(self) -> None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            heartbeat = session.get(ServiceHeartbeat, self._service_name)
            if heartbeat:
                heartbeat.updated_at = now
                heartbeat.host = self._host
                heartbeat.pid = self._pid
                session.add(heartbeat)
                return

            session.add(
                ServiceHeartbeat(
                    service_name=self._service_name,
                    updated_at=now,
                    host=self._host,
                    pid=self._pid,
                )
            )

    def _claim_job(self, job_id: int) -> bool:
        lock_timeout = timedelta(seconds=settings.report_job_lock_timeout_seconds)
        now = datetime.now(timezone.utc)
        lock_token = uuid.uuid4().hex
        with get_session() as session:
            updated = session.execute(
                update(ReportJob)
                .where(
                    ReportJob.id == job_id,
                    ReportJob.status.in_(
                        [ReportJobStatus.PENDING, ReportJobStatus.IN_PROGRESS]
                    ),
                    (ReportJob.locked_at.is_(None))
                    | (ReportJob.locked_at < now - lock_timeout),
                )
                .values(
                    status=ReportJobStatus.IN_PROGRESS,
                    lock_token=lock_token,
                    locked_at=now,
                )
            )
            if updated.rowcount:
                return True
        return False

    async def _handle_job(self, bot: Bot, job_id: int) -> None:
        report = await report_service.generate_report_by_job(job_id=job_id)
        job_status: ReportJobStatus | None = None
        chat_id: int | None = None
        telegram_user_id: int | None = None
        report_meta = None
        pdf_bytes = None

        with get_session() as session:
            job = session.get(ReportJob, job_id)
            if not job:
                return
            user = session.get(User, job.user_id)
            telegram_user_id = user.telegram_user_id if user else None
            chat_id = job.chat_id
            job_status = job.status
            if job.status in {ReportJobStatus.COMPLETED, ReportJobStatus.FAILED}:
                job.lock_token = None
                job.locked_at = None
                session.add(job)

            if telegram_user_id and job_status:
                screen_manager.update_state(
                    telegram_user_id,
                    report_job_id=str(job.id),
                    report_job_status=job_status.value,
                )

            if (
                job_status == ReportJobStatus.COMPLETED
                and report
                and telegram_user_id
                and chat_id
            ):
                screen_manager.update_state(
                    telegram_user_id,
                    report_text=report.report_text,
                    report_text_canonical=screens_handler._get_report_text_canonical(report),
                    report_model=report.model_used.value if report.model_used else None,
                )
                await screens_handler.show_post_report_screen(
                    bot=bot,
                    chat_id=chat_id,
                    user_id=telegram_user_id,
                )
                report_meta = screens_handler._get_report_pdf_meta(report)
                pdf_bytes = screens_handler._get_report_pdf_bytes(session, report)

        if (
            job_status == ReportJobStatus.COMPLETED
            and report
            and telegram_user_id
            and chat_id
        ):
            await screens_handler._send_report_pdf(
                bot,
                chat_id,
                report_meta,
                pdf_bytes=pdf_bytes,
                username=None,
                user_id=telegram_user_id,
            )
        elif job_status == ReportJobStatus.FAILED and telegram_user_id and chat_id:
            await screen_manager.show_screen(
                bot=bot,
                chat_id=chat_id,
                user_id=telegram_user_id,
                screen_id="S6",
                trigger_type="job",
                trigger_value=f"report_job:{job_id}:failed",
                metadata_json={
                    "report_job_status": ReportJobStatus.FAILED.value,
                    "reason": "report_job_failed",
                },
            )


report_job_worker = ReportJobWorker()
