from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.models import ReportJob, ReportJobStatus, ServiceHeartbeat
from app.db.session import get_session

router = APIRouter(tags=["health"])

_WORKER_SERVICE_NAME = "report_jobs_worker"


@router.get("/health/report-worker")
async def report_worker_health() -> dict[str, object]:
    ttl_seconds = max(settings.report_job_poll_interval_seconds * 3, 30)
    stale_after = datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)
    response: dict[str, object] = {
        "alive": False,
        "last_seen_at": None,
        "jobs": {
            ReportJobStatus.PENDING.value: 0,
            ReportJobStatus.IN_PROGRESS.value: 0,
            ReportJobStatus.FAILED.value: 0,
        },
    }

    try:
        with get_session() as session:
            heartbeat = session.get(ServiceHeartbeat, _WORKER_SERVICE_NAME)
            if heartbeat:
                response["last_seen_at"] = heartbeat.updated_at.isoformat()
                response["alive"] = heartbeat.updated_at >= stale_after
    except SQLAlchemyError as exc:
        response["reason"] = f"heartbeat_unavailable: {exc.__class__.__name__}"

    try:
        with get_session() as session:
            rows = session.execute(
                select(ReportJob.status, func.count(ReportJob.id))
                .where(
                    ReportJob.status.in_(
                        [
                            ReportJobStatus.PENDING,
                            ReportJobStatus.IN_PROGRESS,
                            ReportJobStatus.FAILED,
                        ]
                    )
                )
                .group_by(ReportJob.status)
            ).all()
            jobs = response["jobs"]
            if isinstance(jobs, dict):
                for status, count in rows:
                    jobs[status.value] = count
    except SQLAlchemyError as exc:
        response["jobs_reason"] = f"report_jobs_unavailable: {exc.__class__.__name__}"

    return response
