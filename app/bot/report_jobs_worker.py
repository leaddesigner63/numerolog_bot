from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy import select, update

from app.bot.handlers import screens as screens_handler
from app.bot.handlers.screen_manager import screen_manager
from app.core.config import settings
from app.core.report_service import report_service
from app.db.models import ReportJob, ReportJobStatus, User
from app.db.session import get_session


class ReportJobWorker:
    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    async def run(self, bot: Bot) -> None:
        poll_interval = max(settings.report_job_poll_interval_seconds, 1)
        while True:
            try:
                await self._process_pending_jobs(bot)
            except Exception as exc:
                self._logger.warning(
                    "report_job_worker_failed",
                    extra={"error": str(exc)},
                    exc_info=True,
                )
            await asyncio.sleep(poll_interval)

    async def _process_pending_jobs(self, bot: Bot) -> None:
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
