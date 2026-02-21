#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import Text, cast, func, or_, select

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from app.db.models import (
        AdminFinanceEvent,
        FeedbackMessage,
        FreeLimit,
        MarketingConsentEvent,
        Order,
        QuestionnaireResponse,
        Report,
        ReportJob,
        ScreenStateRecord,
        SupportDialogMessage,
        User,
        UserFirstTouchAttribution,
        UserProfile,
    )
    from app.db.session import get_session
except Exception as exc:  # pragma: no cover - защитный путь для окружения
    print(f"[smoke_residuals] stage=bootstrap_error error={exc.__class__.__name__}: {exc}", flush=True)
    sys.exit(1)


def _collect_smoke_ids() -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    with get_session() as session:
        smoke_order_ids = set(
            session.execute(
                select(Order.id).where(or_(Order.is_smoke_check.is_(True), Order.provider_payment_id.like("smoke-%")))
            )
            .scalars()
            .all()
        )
        smoke_order_user_ids = set(
            session.execute(
                select(Order.user_id).where(or_(Order.is_smoke_check.is_(True), Order.provider_payment_id.like("smoke-%")))
            )
            .scalars()
            .all()
        )
        smoke_profile_user_ids = set(
            session.execute(select(UserProfile.user_id).where(UserProfile.name == "Smoke Check")).scalars().all()
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
            session.execute(select(User.id).where(User.telegram_user_id.in_(smoke_state_telegram_ids))).scalars().all()
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

    return smoke_user_ids, smoke_telegram_ids, smoke_order_ids, smoke_report_ids, smoke_job_ids


def main() -> int:
    try:
        smoke_user_ids, smoke_telegram_ids, smoke_order_ids, smoke_report_ids, smoke_job_ids = _collect_smoke_ids()
        with get_session() as session:
            counts = {
                "users": session.execute(select(func.count(User.id)).where(User.id.in_(smoke_user_ids))).scalar_one(),
                "user_profile": session.execute(
                    select(func.count(UserProfile.user_id)).where(UserProfile.user_id.in_(smoke_user_ids))
                ).scalar_one(),
                "orders": session.execute(select(func.count(Order.id)).where(Order.id.in_(smoke_order_ids))).scalar_one(),
                "reports": session.execute(
                    select(func.count(Report.id)).where(or_(Report.id.in_(smoke_report_ids), Report.user_id.in_(smoke_user_ids)))
                ).scalar_one(),
                "report_jobs": session.execute(
                    select(func.count(ReportJob.id)).where(
                        or_(ReportJob.id.in_(smoke_job_ids), ReportJob.user_id.in_(smoke_user_ids))
                    )
                ).scalar_one(),
                "screen_states": session.execute(
                    select(func.count(ScreenStateRecord.telegram_user_id)).where(
                        ScreenStateRecord.telegram_user_id.in_(smoke_telegram_ids)
                    )
                ).scalar_one(),
                "questionnaire_responses": session.execute(
                    select(func.count(QuestionnaireResponse.id)).where(QuestionnaireResponse.user_id.in_(smoke_user_ids))
                ).scalar_one(),
                "feedback_messages": session.execute(
                    select(func.count(FeedbackMessage.id)).where(FeedbackMessage.user_id.in_(smoke_user_ids))
                ).scalar_one(),
                "marketing_consent_events": session.execute(
                    select(func.count(MarketingConsentEvent.id)).where(MarketingConsentEvent.user_id.in_(smoke_user_ids))
                ).scalar_one(),
                "free_limits": session.execute(
                    select(func.count(FreeLimit.id)).where(FreeLimit.user_id.in_(smoke_user_ids))
                ).scalar_one(),
                "support_dialog_messages": session.execute(
                    select(func.count(SupportDialogMessage.id)).where(SupportDialogMessage.user_id.in_(smoke_user_ids))
                ).scalar_one(),
                "admin_finance_events": session.execute(
                    select(func.count(AdminFinanceEvent.id)).where(AdminFinanceEvent.order_id.in_(smoke_order_ids))
                ).scalar_one(),
                "user_first_touch_attribution": session.execute(
                    select(func.count(UserFirstTouchAttribution.id)).where(
                        UserFirstTouchAttribution.telegram_user_id.in_(smoke_telegram_ids)
                    )
                ).scalar_one(),
            }
    except Exception as exc:
        print(f"[smoke_residuals] stage=check_error error={exc.__class__.__name__}: {exc}", flush=True)
        return 1

    non_zero = {table: int(count) for table, count in counts.items() if int(count) > 0}
    for table, count in counts.items():
        print(f"[smoke_residuals] table={table} count={int(count)}", flush=True)

    if non_zero:
        details = ", ".join(f"{table}={count}" for table, count in sorted(non_zero.items()))
        print(f"[smoke_residuals] stage=failed leftovers_detected={details}", flush=True)
        return 1

    print("[smoke_residuals] stage=ok leftovers_detected=0", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
