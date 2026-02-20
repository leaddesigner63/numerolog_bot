#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.bot.handlers.start import _create_paid_order_report_job
from app.db.models import (
    Order,
    OrderFulfillmentStatus,
    OrderStatus,
    PaymentConfirmationSource,
    PaymentProvider,
    ReportJob,
    ReportJobStatus,
    ScreenStateRecord,
    Tariff,
    User,
)
from app.db.session import get_session


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _log(stage: str, **payload: object) -> None:
    details = " ".join(f"{k}={v}" for k, v in payload.items())
    print(f"[smoke_report_job] stage={stage} {details}".strip(), flush=True)


def _prepare_paid_order_and_job() -> tuple[int, int, int]:
    now = datetime.now(timezone.utc)
    telegram_user_id = int(f"97{int(now.timestamp())}")

    with get_session() as session:
        user = User(telegram_user_id=telegram_user_id)
        session.add(user)
        session.flush()

        order = Order(
            user_id=user.id,
            tariff=Tariff.T1,
            amount=1,
            currency="RUB",
            provider=PaymentProvider.NONE,
            provider_payment_id=f"smoke-{now.strftime('%Y%m%d%H%M%S')}",
            status=OrderStatus.PAID,
            paid_at=now,
            payment_confirmed=True,
            payment_confirmed_at=now,
            payment_confirmation_source=PaymentConfirmationSource.SYSTEM,
            fulfillment_status=OrderFulfillmentStatus.PENDING,
        )
        session.add(order)
        session.flush()

        state = session.get(ScreenStateRecord, telegram_user_id)
        if state is None:
            state = ScreenStateRecord(
                telegram_user_id=telegram_user_id,
                data={},
            )
        state.data = {
            "selected_tariff": Tariff.T1.value,
            "order_id": str(order.id),
            "profile": {
                "name": "Smoke Check",
                "birth_date": "01.01.1990",
                "birth_time": "00:00",
                "birth_place": {"city": "Moscow", "country": "RU"},
            },
        }
        session.add(state)

        job = _create_paid_order_report_job(
            session,
            order=order,
            chat_id=telegram_user_id,
        )
        session.flush()

        _log(
            "prepared",
            user_id=user.id,
            telegram_user_id=telegram_user_id,
            order_id=order.id,
            job_id=job.id,
            job_status=job.status.value,
        )
        return user.id, order.id, job.id


def _wait_for_completion(*, job_id: int, timeout_seconds: int, poll_interval_seconds: int) -> int:
    deadline = time.monotonic() + timeout_seconds
    attempt = 0

    while True:
        attempt += 1
        with get_session() as session:
            job = session.get(ReportJob, job_id)
            if job is None:
                _log("job_missing", job_id=job_id)
                return 1

            _log(
                "poll",
                attempt=attempt,
                job_id=job.id,
                status=job.status.value,
                attempts=job.attempts,
                last_error=job.last_error,
                updated_at=job.updated_at,
            )

            if job.status == ReportJobStatus.COMPLETED:
                report_exists = (
                    session.execute(
                        select(Order.fulfilled_report_id).where(Order.id == job.order_id).limit(1)
                    )
                    .scalars()
                    .first()
                )
                _log(
                    "completed",
                    job_id=job.id,
                    fulfilled_report_id=report_exists,
                )
                return 0

            if job.status == ReportJobStatus.FAILED:
                _log("failed", job_id=job.id, last_error=job.last_error)
                return 1

        if time.monotonic() >= deadline:
            _log(
                "timeout",
                job_id=job_id,
                timeout_seconds=timeout_seconds,
                terminal_status="pending_or_in_progress",
            )
            return 1

        time.sleep(max(1, poll_interval_seconds))


def main() -> int:
    timeout_seconds = max(30, _env_int("SMOKE_REPORT_JOB_TIMEOUT_SECONDS", 180))
    poll_interval_seconds = max(1, _env_int("SMOKE_REPORT_JOB_POLL_INTERVAL_SECONDS", 5))

    _log(
        "start",
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )

    try:
        _, order_id, job_id = _prepare_paid_order_and_job()
    except Exception as exc:
        _log("prepare_error", error=f"{exc.__class__.__name__}: {exc}")
        return 1

    _log("job_created", order_id=order_id, job_id=job_id)
    return _wait_for_completion(
        job_id=job_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


if __name__ == "__main__":
    sys.exit(main())
