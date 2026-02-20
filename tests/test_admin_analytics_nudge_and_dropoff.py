from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import (
    Order,
    OrderStatus,
    PaymentConfirmationSource,
    PaymentProvider,
    ScreenStateRecord,
    ScreenTransitionEvent,
    ScreenTransitionTriggerType,
    Tariff,
    User,
)
from app.services.admin_analytics import (
    AnalyticsFilters,
    FinanceAnalyticsFilters,
    build_finance_analytics,
    build_screen_transition_analytics,
)


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine), engine


def test_top_3_dropoff_screens() -> None:
    SessionLocal, engine = _session_factory()
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with SessionLocal() as session:
        session.add_all(
            [
                ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=1,
                    from_screen_id="S0",
                    to_screen_id="S1",
                    trigger_type=ScreenTransitionTriggerType.CALLBACK,
                ),
                ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=2,
                    from_screen_id="S1",
                    to_screen_id="S3",
                    trigger_type=ScreenTransitionTriggerType.CALLBACK,
                ),
                ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=3,
                    from_screen_id="S3",
                    to_screen_id="S5",
                    trigger_type=ScreenTransitionTriggerType.CALLBACK,
                ),
                ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=4,
                    from_screen_id="S0",
                    to_screen_id="S1",
                    trigger_type=ScreenTransitionTriggerType.CALLBACK,
                ),
            ]
        )
        session.flush()
        for idx, event in enumerate(
            session.query(ScreenTransitionEvent).order_by(ScreenTransitionEvent.id.asc()).all()
        ):
            event.created_at = base_time + timedelta(hours=idx * 2)
        session.commit()

        result = build_screen_transition_analytics(
            session,
            AnalyticsFilters(dropoff_window_minutes=30),
        )

    assert len(result["top_dropoff_screens"]) == 3
    assert result["top_dropoff_screens"][0]["screen"] == "S1"
    assert result["top_dropoff_screens"][0]["stage_hint"] == "before_tariff_selection"
    engine.dispose()


def test_finance_resume_after_nudge_uplift() -> None:
    SessionLocal, engine = _session_factory()
    resume_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    with SessionLocal() as session:
        session.add(User(id=1, telegram_user_id=501))
        session.add(
            ScreenStateRecord(
                telegram_user_id=501,
                screen_id="S3",
                message_ids=[],
                user_message_ids=[],
                last_question_message_id=None,
                data={"resume_after_nudge_at": resume_at.isoformat(), "selected_tariff": "T1"},
            )
        )
        session.add(
            Order(
                user_id=1,
                tariff=Tariff.T1,
                amount=990,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                payment_confirmed=True,
                payment_confirmation_source=PaymentConfirmationSource.PROVIDER_WEBHOOK,
                payment_confirmed_at=resume_at + timedelta(hours=1),
            )
        )
        session.commit()

        result = build_finance_analytics(session, FinanceAnalyticsFilters())

    assert result["summary"]["resume_after_nudge_users"] == 1
    assert result["summary"]["resume_after_nudge_paid_users"] == 1
    assert result["summary"]["resume_after_nudge_to_paid"] == 1.0
    engine.dispose()


def test_finance_resume_after_nudge_uplift_by_tariff() -> None:
    SessionLocal, engine = _session_factory()
    resume_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    with SessionLocal() as session:
        session.add(User(id=1, telegram_user_id=601))
        session.add(
            ScreenStateRecord(
                telegram_user_id=601,
                screen_id="S3",
                message_ids=[],
                user_message_ids=[],
                last_question_message_id=None,
                data={"resume_after_nudge_at": resume_at.isoformat(), "selected_tariff": "T2"},
            )
        )
        session.add(
            Order(
                user_id=1,
                tariff=Tariff.T2,
                amount=2190,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                payment_confirmed=True,
                payment_confirmation_source=PaymentConfirmationSource.PROVIDER_WEBHOOK,
                payment_confirmed_at=resume_at + timedelta(hours=2),
            )
        )
        session.commit()

        result = build_finance_analytics(session, FinanceAnalyticsFilters())

    by_tariff = {item["tariff"]: item for item in result["resume_after_nudge_by_tariff"]}
    assert by_tariff["T2"]["resume_users"] == 1
    assert by_tariff["T2"]["paid_users"] == 1
    assert by_tariff["T2"]["resume_to_paid"] == 1.0
    assert by_tariff["T1"]["resume_users"] == 0
    engine.dispose()
