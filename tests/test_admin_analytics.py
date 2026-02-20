import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.admin_analytics import (
    AnalyticsFilters,
    FinanceAnalyticsFilters,
    MarketingAnalyticsFilters,
    build_finance_analytics,
    build_marketing_subscription_analytics,
    build_screen_transition_analytics,
    build_traffic_analytics,
    TrafficAnalyticsFilters,
)
from app.db.base import Base
from app.db.models import ScreenTransitionEvent, ScreenTransitionTriggerType


class AdminAnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_empty_result(self) -> None:
        with self.Session() as session:
            result = build_screen_transition_analytics(session, AnalyticsFilters())

        self.assertEqual(result["summary"]["events"], 0)
        self.assertEqual(result["transition_matrix"], [])
        self.assertEqual(result["funnel"], [])
        self.assertEqual(result["dropoff"], [])
        self.assertEqual(result["transition_durations"], [])

    def test_aggregations_and_unknown_screen(self) -> None:
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with self.Session() as session:
            session.add_all(
                [
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=1,
                        from_screen_id="S0",
                        to_screen_id="S1",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T1"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=1,
                        from_screen_id="S1",
                        to_screen_id="S3",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T1"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=1,
                        from_screen_id="S3",
                        to_screen_id="S5",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T1"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=2,
                        from_screen_id="S0",
                        to_screen_id="S1",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T2"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=2,
                        from_screen_id="bad_screen",
                        to_screen_id=None,
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T2"},
                    ),
                ]
            )
            session.flush()
            events = (
                session.query(ScreenTransitionEvent)
                .order_by(ScreenTransitionEvent.telegram_user_id.asc(), ScreenTransitionEvent.id.asc())
                .all()
            )
            for idx, event in enumerate(events):
                event.created_at = base_time + timedelta(minutes=idx * 2)
            session.commit()

            result = build_screen_transition_analytics(
                session,
                AnalyticsFilters(tariff="T2", unique_users_only=True, dropoff_window_minutes=1),
            )

        self.assertEqual(result["summary"]["events"], 2)
        self.assertEqual(result["summary"]["users"], 1)

        matrix_pairs = {(item["from_screen"], item["to_screen"]): item for item in result["transition_matrix"]}
        self.assertIn(("S0", "S1"), matrix_pairs)
        self.assertIn(("UNKNOWN", "UNKNOWN"), matrix_pairs)

        funnel = {item["step"]: item["users"] for item in result["funnel"]}
        self.assertEqual(funnel["S0"], 1)
        self.assertEqual(funnel["S1"], 1)

        self.assertTrue(result["dropoff"])
        duration_pairs = {(item["from_screen"], item["to_screen"]) for item in result["transition_durations"]}
        self.assertIn(("S1", "UNKNOWN"), duration_pairs)


    def test_funnel_templates_by_tariff(self) -> None:
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with self.Session() as session:
            session.add_all(
                [
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=11,
                        from_screen_id="S0",
                        to_screen_id="S1",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T1"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=11,
                        from_screen_id="S1",
                        to_screen_id="S3",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T1"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=11,
                        from_screen_id="S3",
                        to_screen_id="S6",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T1"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=22,
                        from_screen_id="S0",
                        to_screen_id="S1",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T2"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=22,
                        from_screen_id="S1",
                        to_screen_id="S5",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T2"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=22,
                        from_screen_id="S5",
                        to_screen_id="S3",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T2"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=22,
                        from_screen_id="S3",
                        to_screen_id="S7",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T2"},
                    ),
                ]
            )
            session.flush()
            events = session.query(ScreenTransitionEvent).order_by(ScreenTransitionEvent.id.asc()).all()
            for idx, event in enumerate(events):
                event.created_at = base_time + timedelta(minutes=idx)
            session.commit()

            result = build_screen_transition_analytics(session, AnalyticsFilters())

        self.assertIn("funnel_by_tariff", result)
        self.assertEqual([item["step"] for item in result["funnel_by_tariff"]["T1"]], ["S0", "S1", "S3", "S6_OR_S7"])
        self.assertEqual([item["step"] for item in result["funnel_by_tariff"]["T2"]], ["S0", "S1", "S5", "S3", "S6_OR_S7"])
        self.assertEqual(result["funnel_by_tariff"]["T2"][2]["users"], 1)
        self.assertEqual(result["funnel_by_tariff"]["T0"], [])

    def test_finance_layer_provider_confirmed_only(self) -> None:
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        from app.db.models import (
            Order,
            OrderStatus,
            PaymentConfirmationSource,
            PaymentProvider,
            Tariff,
            User,
        )
        with self.Session() as session:
            session.add_all([
                User(id=1, telegram_user_id=1001),
                User(id=2, telegram_user_id=1002),
            ])
            session.add_all([
                ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=1001,
                    from_screen_id="S1",
                    to_screen_id="S3",
                    trigger_type=ScreenTransitionTriggerType.CALLBACK,
                    metadata_json={"tariff": "T1"},
                ),
                ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=1002,
                    from_screen_id="S1",
                    to_screen_id="S4",
                    trigger_type=ScreenTransitionTriggerType.CALLBACK,
                    metadata_json={"tariff": "T1"},
                ),
                ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=1001,
                    from_screen_id="S3",
                    to_screen_id="S3_INFO",
                    trigger_type=ScreenTransitionTriggerType.CALLBACK,
                    trigger_value="s3:report_details",
                    metadata_json={"tariff": "T1"},
                ),
                ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=1002,
                    from_screen_id="S3",
                    to_screen_id="S3_INFO",
                    trigger_type=ScreenTransitionTriggerType.CALLBACK,
                    trigger_value="s3:report_details",
                    metadata_json={"tariff": "T1"},
                ),
                Order(
                    user_id=1,
                    tariff=Tariff.T1,
                    amount=1200,
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PAID,
                    payment_confirmed=True,
                    payment_confirmation_source=PaymentConfirmationSource.PROVIDER_WEBHOOK,
                    payment_confirmed_at=base_time + timedelta(hours=1),
                ),
                Order(
                    user_id=2,
                    tariff=Tariff.T1,
                    amount=900,
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PAID,
                    payment_confirmed=True,
                    payment_confirmation_source=PaymentConfirmationSource.ADMIN_MANUAL,
                    payment_confirmed_at=base_time + timedelta(hours=2),
                ),
            ])
            session.flush()
            for idx, event in enumerate(session.query(ScreenTransitionEvent).order_by(ScreenTransitionEvent.id.asc()).all()):
                event.created_at = base_time + timedelta(minutes=idx)
            session.commit()

            result = build_finance_analytics(session, FinanceAnalyticsFilters(from_dt=base_time - timedelta(days=1), to_dt=base_time + timedelta(days=1), tariff="T1"))

        self.assertEqual(result["summary"]["entry_users"], 2)
        self.assertEqual(result["summary"]["provider_confirmed_orders"], 1)
        self.assertEqual(result["summary"]["provider_confirmed_revenue"], 1200.0)
        self.assertEqual(result["summary"]["s3_report_details_clicks"], 2)
        self.assertEqual(result["summary"]["s3_report_details_users"], 2)
        self.assertEqual(result["by_tariff"][0]["tariff"], "T1")


    def test_marketing_subscription_analytics(self) -> None:
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        from app.db.models import MarketingConsentEvent, MarketingConsentEventType, User, UserProfile

        with self.Session() as session:
            session.add_all([
                User(id=1, telegram_user_id=1001),
                User(id=2, telegram_user_id=1002),
                User(id=3, telegram_user_id=1003),
            ])
            session.add_all([
                UserProfile(
                    user_id=1,
                    name="A",
                    birth_date="2000-01-01",
                    birth_place_city="M",
                    birth_place_country="RU",
                    marketing_consent_accepted_at=base_time,
                    marketing_consent_document_version="v1",
                ),
                UserProfile(
                    user_id=2,
                    name="B",
                    birth_date="2000-01-01",
                    birth_place_city="M",
                    birth_place_country="RU",
                    marketing_consent_accepted_at=base_time,
                    marketing_consent_revoked_at=base_time + timedelta(days=1),
                    marketing_consent_document_version="v1",
                ),
            ])
            session.add_all([
                MarketingConsentEvent(
                    user_id=1,
                    event_type=MarketingConsentEventType.ACCEPTED,
                    event_at=base_time + timedelta(hours=1),
                    source="marketing_prompt",
                ),
                MarketingConsentEvent(
                    user_id=2,
                    event_type=MarketingConsentEventType.REVOKED,
                    event_at=base_time + timedelta(hours=2),
                    source="marketing_prompt",
                ),
            ])
            session.add_all([
                ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=1001,
                    from_screen_id="S3",
                    to_screen_id="S4",
                    trigger_type=ScreenTransitionTriggerType.CALLBACK,
                ),
                ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=1002,
                    from_screen_id="S3",
                    to_screen_id="S4",
                    trigger_type=ScreenTransitionTriggerType.CALLBACK,
                ),
            ])
            session.flush()
            for idx, event in enumerate(session.query(ScreenTransitionEvent).order_by(ScreenTransitionEvent.id.asc()).all()):
                event.created_at = base_time + timedelta(minutes=idx)
            session.commit()

            result = build_marketing_subscription_analytics(
                session,
                MarketingAnalyticsFilters(
                    from_dt=base_time - timedelta(days=1),
                    to_dt=base_time + timedelta(days=2),
                ),
            )

        self.assertEqual(result["total_subscribed"], 1)
        self.assertEqual(result["new_subscribes_per_period"], 1)
        self.assertEqual(result["unsubscribes_per_period"], 1)
        self.assertEqual(result["prompted_users_per_period"], 2)
        self.assertEqual(result["subscribed_from_prompt_per_period"], 1)
        self.assertEqual(result["prompt_to_subscribe_conversion_rate"], 0.5)

    def test_admin_users_are_excluded_from_transition_analytics(self) -> None:
        with self.Session() as session:
            session.add_all(
                [
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=999,
                        from_screen_id="S0",
                        to_screen_id="S1",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T1"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=100,
                        from_screen_id="S0",
                        to_screen_id="S1",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T1"},
                    ),
                ]
            )
            session.commit()

            with patch("app.services.admin_analytics.settings.admin_ids", "999"):
                result = build_screen_transition_analytics(session, AnalyticsFilters())

        self.assertEqual(result["summary"]["events"], 1)
        self.assertEqual(result["summary"]["users"], 1)

    def test_admin_users_are_excluded_from_finance_analytics_entry_users(self) -> None:
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        from app.db.models import User

        with self.Session() as session:
            session.add_all([
                User(id=1, telegram_user_id=999),
                User(id=2, telegram_user_id=100),
            ])
            session.add_all(
                [
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=999,
                        from_screen_id="S1",
                        to_screen_id="S3",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T1"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=100,
                        from_screen_id="S1",
                        to_screen_id="S3",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T1"},
                    ),
                ]
            )
            session.flush()
            for event in session.query(ScreenTransitionEvent).order_by(ScreenTransitionEvent.id.asc()).all():
                event.created_at = base_time
            session.commit()

            with patch("app.services.admin_analytics.settings.admin_ids", "999"):
                result = build_finance_analytics(session, FinanceAnalyticsFilters())

        self.assertEqual(result["summary"]["entry_users"], 1)


    def test_traffic_analytics_empty_is_safe(self) -> None:
        with self.Session() as session:
            result = build_traffic_analytics(session, TrafficAnalyticsFilters())

        self.assertEqual(result["users_started_total"], 0)
        self.assertEqual(result["users_by_source"], [])
        self.assertEqual(result["users_by_source_campaign"], [])
        self.assertEqual(result["conversions"], [])

    def test_traffic_analytics_first_touch_breakdown_and_conversion(self) -> None:
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        from app.db.models import (
            Order,
            OrderStatus,
            PaymentConfirmationSource,
            PaymentProvider,
            Tariff,
            User,
            UserFirstTouchAttribution,
        )

        with self.Session() as session:
            session.add_all([
                User(id=1, telegram_user_id=1001),
                User(id=2, telegram_user_id=1002),
                User(id=3, telegram_user_id=1003),
            ])
            session.add_all([
                UserFirstTouchAttribution(
                    telegram_user_id=1001,
                    start_payload="src=ads",
                    source="ads",
                    campaign="winter",
                    captured_at=base_time,
                ),
                UserFirstTouchAttribution(
                    telegram_user_id=1002,
                    start_payload="src=ads",
                    source="ads",
                    campaign=None,
                    captured_at=base_time + timedelta(minutes=1),
                ),
                UserFirstTouchAttribution(
                    telegram_user_id=1003,
                    start_payload="raw",
                    source=None,
                    campaign="campaign-x",
                    captured_at=base_time + timedelta(minutes=2),
                ),
            ])
            session.add_all([
                ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=1001,
                    from_screen_id="S1",
                    to_screen_id="S3",
                    trigger_type=ScreenTransitionTriggerType.CALLBACK,
                    metadata_json={"tariff": "T1"},
                ),
                ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=1002,
                    from_screen_id="S1",
                    to_screen_id="S4",
                    trigger_type=ScreenTransitionTriggerType.CALLBACK,
                    metadata_json={"tariff": "T1"},
                ),
                ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=1001,
                    from_screen_id="S3",
                    to_screen_id="S3_INFO",
                    trigger_type=ScreenTransitionTriggerType.CALLBACK,
                    trigger_value="s3:report_details",
                    metadata_json={"tariff": "T1"},
                ),
                ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=1002,
                    from_screen_id="S3",
                    to_screen_id="S3_INFO",
                    trigger_type=ScreenTransitionTriggerType.CALLBACK,
                    trigger_value="s3:report_details",
                    metadata_json={"tariff": "T1"},
                ),
            ])
            session.add(
                Order(
                    user_id=1,
                    tariff=Tariff.T1,
                    amount=1000,
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PAID,
                    payment_confirmed=True,
                    payment_confirmation_source=PaymentConfirmationSource.PROVIDER_WEBHOOK,
                    payment_confirmed_at=base_time + timedelta(hours=1),
                )
            )
            session.flush()
            for idx, event in enumerate(session.query(ScreenTransitionEvent).order_by(ScreenTransitionEvent.id.asc()).all()):
                event.created_at = base_time + timedelta(minutes=idx + 1)
            session.commit()

            result = build_traffic_analytics(
                session,
                TrafficAnalyticsFilters(
                    from_dt=base_time - timedelta(days=1),
                    to_dt=base_time + timedelta(days=1),
                    tariff="T1",
                ),
            )

        self.assertEqual(result["users_started_total"], 2)
        self.assertEqual(result["users_by_source"][0], {"source": "ads", "users": 2, "conversion_to_paid": 0.5})
        self.assertEqual(result["users_by_source_campaign"][0], {"source": "ads", "campaign": "UNKNOWN", "users": 1, "conversion": 0.0})
        conversion = {row["step"]: row for row in result["conversions"]}
        self.assertEqual(conversion["started"]["users"], 2)
        self.assertEqual(conversion["reached_tariff"]["users"], 2)
        self.assertEqual(conversion["paid"]["users"], 1)
        self.assertEqual(conversion["paid"]["conversion_from_start"], 0.5)

    def test_traffic_analytics_aggregates_source_campaign_and_conversion_rates(self) -> None:
        base_time = datetime(2026, 2, 1, tzinfo=timezone.utc)
        from app.db.models import (
            Order,
            OrderStatus,
            PaymentConfirmationSource,
            PaymentProvider,
            Tariff,
            User,
            UserFirstTouchAttribution,
        )

        with self.Session() as session:
            session.add_all(
                [
                    User(id=11, telegram_user_id=5011),
                    User(id=12, telegram_user_id=5012),
                    User(id=13, telegram_user_id=5013),
                    User(id=14, telegram_user_id=5014),
                ]
            )
            session.add_all(
                [
                    UserFirstTouchAttribution(
                        telegram_user_id=5011,
                        start_payload="src_vk_cmp_winter",
                        source="vk",
                        campaign="winter",
                        captured_at=base_time,
                    ),
                    UserFirstTouchAttribution(
                        telegram_user_id=5012,
                        start_payload="src_vk_cmp_winter",
                        source="vk",
                        campaign="winter",
                        captured_at=base_time + timedelta(minutes=1),
                    ),
                    UserFirstTouchAttribution(
                        telegram_user_id=5013,
                        start_payload="src_vk_cmp_spring",
                        source="vk",
                        campaign="spring",
                        captured_at=base_time + timedelta(minutes=2),
                    ),
                    UserFirstTouchAttribution(
                        telegram_user_id=5014,
                        start_payload="direct",
                        source=None,
                        campaign=None,
                        captured_at=base_time + timedelta(minutes=3),
                    ),
                ]
            )
            session.add_all(
                [
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=5011,
                        from_screen_id="S1",
                        to_screen_id="S3",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T2"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=5012,
                        from_screen_id="S1",
                        to_screen_id="S4",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T2"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=5013,
                        from_screen_id="S1",
                        to_screen_id="S3",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T2"},
                    ),
                ]
            )
            session.add_all(
                [
                    Order(
                        user_id=11,
                        tariff=Tariff.T2,
                        amount=1200,
                        currency="RUB",
                        provider=PaymentProvider.PRODAMUS,
                        status=OrderStatus.PAID,
                        payment_confirmed=True,
                        payment_confirmation_source=PaymentConfirmationSource.PROVIDER_WEBHOOK,
                        payment_confirmed_at=base_time + timedelta(hours=2),
                    ),
                    Order(
                        user_id=13,
                        tariff=Tariff.T2,
                        amount=1200,
                        currency="RUB",
                        provider=PaymentProvider.PRODAMUS,
                        status=OrderStatus.PAID,
                        payment_confirmed=True,
                        payment_confirmation_source=PaymentConfirmationSource.PROVIDER_WEBHOOK,
                        payment_confirmed_at=base_time + timedelta(hours=3),
                    ),
                ]
            )
            session.flush()
            for idx, event in enumerate(session.query(ScreenTransitionEvent).order_by(ScreenTransitionEvent.id.asc()).all()):
                event.created_at = base_time + timedelta(minutes=idx)
            session.commit()

            result = build_traffic_analytics(
                session,
                TrafficAnalyticsFilters(
                    from_dt=base_time - timedelta(days=1),
                    to_dt=base_time + timedelta(days=1),
                    tariff="T2",
                ),
            )

        self.assertEqual(result["users_started_total"], 3)
        self.assertEqual(
            result["users_by_source"],
            [
                {"source": "vk", "users": 3, "conversion_to_paid": 0.666667},
            ],
        )
        self.assertEqual(
            result["users_by_source_campaign"],
            [
                {"source": "vk", "campaign": "winter", "users": 2, "conversion": 0.5},
                {"source": "vk", "campaign": "spring", "users": 1, "conversion": 1.0},
            ],
        )
        conversion = {row["step"]: row for row in result["conversions"]}
        self.assertEqual(conversion["started"]["users"], 3)
        self.assertEqual(conversion["reached_tariff"]["users"], 3)
        self.assertEqual(conversion["paid"]["users"], 2)
        self.assertEqual(conversion["paid"]["conversion_from_start"], 0.666667)


    def test_traffic_analytics_builds_paid_per_tariff_click_slice(self) -> None:
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        from app.db.models import PaymentConfirmationSource, PaymentProvider, Tariff, User, UserFirstTouchAttribution, Order, OrderStatus

        with self.Session() as session:
            session.add_all([
                User(id=401, telegram_user_id=4401),
                User(id=402, telegram_user_id=4402),
                User(id=403, telegram_user_id=4403),
            ])
            session.add_all([
                UserFirstTouchAttribution(
                    telegram_user_id=4401,
                    source="vk",
                    campaign="cmp_a",
                    placement="tariff_t1",
                    start_payload="lnd.src_vk.cmp_cmp_a.pl_tariff_t1",
                    captured_at=base_time,
                ),
                UserFirstTouchAttribution(
                    telegram_user_id=4402,
                    source="vk",
                    campaign="cmp_a",
                    placement="tariff_t1",
                    start_payload="lnd.src_vk.cmp_cmp_a.pl_tariff_t1",
                    captured_at=base_time + timedelta(minutes=1),
                ),
                UserFirstTouchAttribution(
                    telegram_user_id=4403,
                    source="vk",
                    campaign="cmp_b",
                    placement="tariff_t2",
                    start_payload="lnd.src_vk.cmp_cmp_b.pl_tariff_t2",
                    captured_at=base_time + timedelta(minutes=2),
                ),
            ])
            session.add(
                Order(
                    user_id=401,
                    tariff=Tariff.T1,
                    amount=560,
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PAID,
                    payment_confirmed=True,
                    payment_confirmation_source=PaymentConfirmationSource.PROVIDER_WEBHOOK,
                    payment_confirmed_at=base_time + timedelta(hours=1),
                )
            )
            session.commit()

            result = build_traffic_analytics(session, TrafficAnalyticsFilters(from_dt=base_time - timedelta(days=1), to_dt=base_time + timedelta(days=1)))

        by_tariff = {item["tariff"]: item for item in result["paid_per_tariff_click"]}
        self.assertEqual(by_tariff["T1"]["tariff_click_users"], 2)
        self.assertEqual(by_tariff["T1"]["paid_users"], 1)
        self.assertEqual(by_tariff["T1"]["paid_per_tariff_click"], 0.5)
        self.assertEqual(by_tariff["T2"]["tariff_click_users"], 1)
        self.assertEqual(by_tariff["T2"]["paid_users"], 0)


if __name__ == "__main__":
    unittest.main()
