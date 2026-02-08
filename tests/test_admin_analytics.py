import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.admin_analytics import AnalyticsFilters, build_screen_transition_analytics
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


if __name__ == "__main__":
    unittest.main()
