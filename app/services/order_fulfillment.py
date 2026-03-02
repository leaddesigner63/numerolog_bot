from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Order, OrderStatus, ReportJob, ReportJobStatus, ScreenStateRecord, Tariff, User

logger = logging.getLogger(__name__)

_PAID_TARIFFS = {Tariff.T1, Tariff.T2, Tariff.T3}


def ensure_report_job_for_paid_order(
    session: Session,
    order_id: int,
    *,
    reason: str,
) -> ReportJob | None:
    order = session.get(Order, order_id)
    if not order:
        logger.info("report_job_ensure_skipped_order_missing", extra={"order_id": order_id, "reason": reason})
        return None
    if order.tariff not in _PAID_TARIFFS:
        logger.info(
            "report_job_ensure_skipped_non_paid_tariff",
            extra={"order_id": order.id, "tariff": order.tariff.value, "reason": reason},
        )
        return None
    if order.status != OrderStatus.PAID:
        logger.info(
            "report_job_ensure_skipped_order_not_paid",
            extra={"order_id": order.id, "status": order.status.value, "reason": reason},
        )
        return None

    chat_id = _resolve_chat_id_for_order(session, order)
    active_job = (
        session.execute(
            select(ReportJob)
            .where(
                ReportJob.order_id == order.id,
                ReportJob.status.in_([ReportJobStatus.PENDING, ReportJobStatus.IN_PROGRESS]),
            )
            .order_by(ReportJob.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if active_job:
        if chat_id is not None and active_job.chat_id != chat_id:
            active_job.chat_id = chat_id
            session.add(active_job)
        logger.info(
            "report_job_ensure_skipped_active_exists",
            extra={"order_id": order.id, "job_id": active_job.id, "reason": reason},
        )
        return active_job

    last_job = (
        session.execute(
            select(ReportJob)
            .where(ReportJob.order_id == order.id)
            .order_by(ReportJob.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if last_job and last_job.status == ReportJobStatus.FAILED:
        last_job.status = ReportJobStatus.PENDING
        last_job.last_error = None
        last_job.lock_token = None
        last_job.locked_at = None
        last_job.attempts = 0
        if chat_id is not None:
            last_job.chat_id = chat_id
        session.add(last_job)
        logger.info(
            "report_job_ensure_requeued_failed",
            extra={"order_id": order.id, "job_id": last_job.id, "reason": reason},
        )
        return last_job

    if last_job and last_job.status == ReportJobStatus.COMPLETED:
        logger.info(
            "report_job_ensure_skipped_completed_exists",
            extra={"order_id": order.id, "job_id": last_job.id, "reason": reason},
        )
        return last_job

    job = ReportJob(
        user_id=order.user_id,
        order_id=order.id,
        tariff=order.tariff,
        status=ReportJobStatus.PENDING,
        attempts=0,
        chat_id=chat_id,
    )
    session.add(job)
    session.flush()
    logger.info(
        "report_job_ensure_created",
        extra={"order_id": order.id, "job_id": job.id, "reason": reason},
    )
    return job


def _resolve_chat_id_for_order(session: Session, order: Order) -> int | None:
    user = session.get(User, order.user_id)
    if not user:
        return None
    state = session.get(ScreenStateRecord, user.telegram_user_id)
    if not state:
        return None
    return user.telegram_user_id
