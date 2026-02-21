#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

from sqlalchemy import Text, cast, delete, or_, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.bot.handlers.start import _create_paid_order_report_job
from app.core.config import settings
from app.db.models import (
    AdminFinanceEvent,
    FeedbackMessage,
    FreeLimit,
    MarketingConsentEvent,
    Order,
    OrderFulfillmentStatus,
    OrderStatus,
    PaymentConfirmationSource,
    PaymentProvider,
    QuestionnaireResponse,
    Report,
    ReportJob,
    ReportJobStatus,
    ScreenStateRecord,
    SupportDialogMessage,
    Tariff,
    User,
    UserFirstTouchAttribution,
    UserProfile,
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


def _prepare_paid_order_and_job() -> tuple[int, int, int, int]:
    now = datetime.now(timezone.utc)
    telegram_user_id = int(f"97{int(now.timestamp())}")

    with get_session() as session:
        user = User(telegram_user_id=telegram_user_id)
        session.add(user)
        session.flush()

        profile = UserProfile(
            user_id=user.id,
            name="Smoke Check",
            gender=None,
            birth_date="01.01.1990",
            birth_time="00:00",
            birth_place_city="Moscow",
            birth_place_region=None,
            birth_place_country="RU",
        )
        session.add(profile)

        paid_amount = settings.tariff_prices_rub.get(Tariff.T1.value, 0)
        order = Order(
            user_id=user.id,
            tariff=Tariff.T1,
            amount=paid_amount,
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
            "smoke_marker": "report_job_completion",
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
        return user.id, telegram_user_id, order.id, job.id


def _collect_smoke_entity_ids() -> tuple[set[int], set[int], set[int], set[int]]:
    with get_session() as session:
        smoke_order_ids = set(
            session.execute(
                select(Order.id).where(Order.provider_payment_id.like("smoke-%"))
            )
            .scalars()
            .all()
        )
        smoke_order_user_ids = set(
            session.execute(
                select(Order.user_id).where(Order.provider_payment_id.like("smoke-%"))
            )
            .scalars()
            .all()
        )

        smoke_profile_user_ids = set(
            session.execute(select(UserProfile.user_id).where(UserProfile.name == "Smoke Check"))
            .scalars()
            .all()
        )

        smoke_state_telegram_ids = set(
            session.execute(
                select(ScreenStateRecord.telegram_user_id).where(
                    cast(ScreenStateRecord.data, Text).like('%"smoke_marker": "report_job_completion"%')
                )
            )
            .scalars()
            .all()
        )

        smoke_state_user_ids = set(
            session.execute(
                select(User.id).where(User.telegram_user_id.in_(smoke_state_telegram_ids))
            )
            .scalars()
            .all()
        )

        smoke_user_ids = smoke_order_user_ids | smoke_profile_user_ids | smoke_state_user_ids
        smoke_telegram_ids = set(
            session.execute(select(User.telegram_user_id).where(User.id.in_(smoke_user_ids))).scalars().all()
        ) | smoke_state_telegram_ids
        smoke_order_ids |= set(
            session.execute(select(Order.id).where(Order.user_id.in_(smoke_user_ids))).scalars().all()
        )
        smoke_report_ids = set(
            session.execute(
                select(Report.id).where(or_(Report.user_id.in_(smoke_user_ids), Report.order_id.in_(smoke_order_ids)))
            )
            .scalars()
            .all()
        )
        smoke_job_ids = set(
            session.execute(
                select(ReportJob.id).where(
                    or_(ReportJob.user_id.in_(smoke_user_ids), ReportJob.order_id.in_(smoke_order_ids))
                )
            )
            .scalars()
            .all()
        )

    _log(
        "cleanup_targets",
        users=len(smoke_user_ids),
        telegram_users=len(smoke_telegram_ids),
        orders=len(smoke_order_ids),
        reports=len(smoke_report_ids),
        report_jobs=len(smoke_job_ids),
    )
    return smoke_user_ids, smoke_telegram_ids, smoke_order_ids, smoke_report_ids


def _cleanup_smoke_entities() -> None:
    smoke_user_ids, smoke_telegram_ids, smoke_order_ids, smoke_report_ids = _collect_smoke_entity_ids()

    if not smoke_user_ids and not smoke_telegram_ids and not smoke_order_ids and not smoke_report_ids:
        _log("cleanup_done", deleted_total=0)
        return

    deleted_counts: dict[str, int] = {}

    def _delete(table_name: str, stmt) -> None:
        with get_session() as session:
            result = session.execute(stmt)
            deleted_counts[table_name] = int(result.rowcount or 0)

    _delete(
        "support_dialog_messages",
        delete(SupportDialogMessage).where(SupportDialogMessage.user_id.in_(smoke_user_ids)),
    )

    _delete(
        "admin_finance_events",
        delete(AdminFinanceEvent).where(AdminFinanceEvent.order_id.in_(smoke_order_ids)),
    )
    _delete(
        "feedback_messages",
        delete(FeedbackMessage).where(FeedbackMessage.user_id.in_(smoke_user_ids)),
    )
    _delete(
        "questionnaire_responses",
        delete(QuestionnaireResponse).where(QuestionnaireResponse.user_id.in_(smoke_user_ids)),
    )
    _delete(
        "marketing_consent_events",
        delete(MarketingConsentEvent).where(MarketingConsentEvent.user_id.in_(smoke_user_ids)),
    )
    _delete("free_limits", delete(FreeLimit).where(FreeLimit.user_id.in_(smoke_user_ids)))
    _delete(
        "user_first_touch_attribution",
        delete(UserFirstTouchAttribution).where(
            UserFirstTouchAttribution.telegram_user_id.in_(smoke_telegram_ids)
        ),
    )
    _delete(
        "report_jobs",
        delete(ReportJob).where(or_(ReportJob.user_id.in_(smoke_user_ids), ReportJob.order_id.in_(smoke_order_ids))),
    )
    _delete(
        "reports",
        delete(Report).where(or_(Report.user_id.in_(smoke_user_ids), Report.id.in_(smoke_report_ids))),
    )
    _delete("orders", delete(Order).where(Order.id.in_(smoke_order_ids)))
    _delete("user_profile", delete(UserProfile).where(UserProfile.user_id.in_(smoke_user_ids)))
    _delete("users", delete(User).where(User.id.in_(smoke_user_ids)))
    _delete(
        "screen_states",
        delete(ScreenStateRecord).where(ScreenStateRecord.telegram_user_id.in_(smoke_telegram_ids)),
    )

    for table_name, count in deleted_counts.items():
        _log("cleanup_table", table=table_name, deleted=count)

    _log("cleanup_done", deleted_total=sum(deleted_counts.values()))


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
    if len(sys.argv) > 1 and sys.argv[1] == "cleanup-only":
        _log("cleanup_only_start")
        try:
            _cleanup_smoke_entities()
        except Exception as exc:
            _log("cleanup_error", error=f"{exc.__class__.__name__}: {exc}")
            return 1
        _log("cleanup_only_done")
        return 0

    timeout_seconds = max(30, _env_int("SMOKE_REPORT_JOB_TIMEOUT_SECONDS", 180))
    poll_interval_seconds = max(1, _env_int("SMOKE_REPORT_JOB_POLL_INTERVAL_SECONDS", 5))

    _log(
        "start",
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )

    user_id: int | None = None
    telegram_user_id: int | None = None
    try:
        user_id, telegram_user_id, order_id, job_id = _prepare_paid_order_and_job()
    except Exception as exc:
        _log("prepare_error", error=f"{exc.__class__.__name__}: {exc}")
        return 1

    _log("job_created", order_id=order_id, job_id=job_id)
    result = 1
    try:
        result = _wait_for_completion(
            job_id=job_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
    except Exception as exc:
        _log("wait_error", job_id=job_id, error=f"{exc.__class__.__name__}: {exc}")
    finally:
        try:
            _cleanup_smoke_entities()
        except Exception as exc:
            _log(
                "cleanup_error",
                user_id=user_id,
                telegram_user_id=telegram_user_id,
                error=f"{exc.__class__.__name__}: {exc}",
            )
            return 1

    return result


if __name__ == "__main__":
    sys.exit(main())
