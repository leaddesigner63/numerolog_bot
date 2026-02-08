import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import admin as admin_routes
from app.db.base import Base
from app.db.models import ScreenTransitionEvent, ScreenTransitionTriggerType
from app.main import create_app


class AdminAnalyticsRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.app = create_app()

        def override_db_session():
            session = self.SessionLocal()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        self.app.dependency_overrides[admin_routes._get_db_session] = override_db_session
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _seed_events(self) -> None:
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with self.SessionLocal() as session:
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
                        telegram_user_id=2,
                        from_screen_id="S0",
                        to_screen_id="S1",
                        trigger_type=ScreenTransitionTriggerType.CALLBACK,
                        metadata_json={"tariff": "T2"},
                    ),
                    ScreenTransitionEvent.build_fail_safe(
                        telegram_user_id=2,
                        from_screen_id="S1",
                        to_screen_id="S5",
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

    def test_transitions_summary_contract(self) -> None:
        self._seed_events()
        response = self.client.get("/admin/api/analytics/transitions/summary")
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertIn("generated_at", payload)
        self.assertIn("filters_applied", payload)
        self.assertIn("data", payload)
        self.assertIn("warnings", payload)
        self.assertEqual(payload["data"]["summary"]["events"], 4)
        self.assertEqual(payload["filters_applied"]["limit"], 5000)

    def test_transitions_matrix_top_n_and_whitelist(self) -> None:
        self._seed_events()
        response = self.client.get(
            "/admin/api/analytics/transitions/matrix",
            params={"top_n": 1, "screen_id": ["S1"]},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["data"]["transition_matrix"]), 1)
        self.assertEqual(payload["filters_applied"]["screen_ids"], ["S1"])

    def test_transitions_validation_errors(self) -> None:
        bad_screen = self.client.get(
            "/admin/api/analytics/transitions/matrix",
            params={"screen_id": ["S999"]},
        )
        self.assertEqual(bad_screen.status_code, 422)

        bad_dates = self.client.get(
            "/admin/api/analytics/transitions/funnel",
            params={
                "from": "2026-01-02T00:00:00Z",
                "to": "2026-01-01T00:00:00Z",
            },
        )
        self.assertEqual(bad_dates.status_code, 422)


if __name__ == "__main__":
    unittest.main()
