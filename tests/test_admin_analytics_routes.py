import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import admin as admin_routes
from app.db.base import Base
from app.db.models import (
    Order,
    OrderFulfillmentStatus,
    OrderStatus,
    PaymentProvider,
    Report,
    ScreenTransitionEvent,
    ScreenTransitionTriggerType,
    Tariff,
    User,
)
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


    def test_orders_payload_includes_fulfillment_fields_and_report_id(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=100, telegram_user_id=700700, telegram_username="manager")
            order = Order(
                id=200,
                user_id=100,
                tariff=Tariff.T2,
                amount=1990,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                fulfillment_status=OrderFulfillmentStatus.PENDING,
            )
            report = Report(
                id=300,
                user_id=100,
                order_id=200,
                tariff=Tariff.T2,
                report_text="report",
            )
            session.add_all([user, order, report])
            session.commit()

        response = self.client.get("/admin/api/orders")
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertIn("orders", payload)
        order_payload = next(item for item in payload["orders"] if item["id"] == 200)
        self.assertEqual(order_payload["fulfillment_status"], OrderFulfillmentStatus.PENDING.value)
        self.assertIsNone(order_payload["fulfilled_at"])
        self.assertEqual(order_payload["report_id"], 300)

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

    def test_transitions_return_503_on_database_overload(self) -> None:
        with patch.object(
            admin_routes,
            "build_screen_transition_analytics",
            side_effect=OperationalError("SELECT 1", {}, Exception("too many clients")),
        ):
            response = self.client.get("/admin/api/analytics/transitions/matrix")

        self.assertEqual(response.status_code, 503)
        self.assertIn("временно перегружена", response.json()["detail"])

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

    def test_admin_order_status_completed_sets_fulfillment(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=101, telegram_user_id=700701)
            order = Order(
                id=201,
                user_id=101,
                tariff=Tariff.T1,
                amount=990,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                fulfillment_status=OrderFulfillmentStatus.PENDING,
            )
            session.add_all([user, order])
            session.commit()

        response = self.client.post("/admin/api/orders/201/status", json={"status": "completed"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["updated"])

        with self.SessionLocal() as session:
            refreshed = session.get(Order, 201)
            self.assertIsNotNone(refreshed)
            self.assertEqual(refreshed.fulfillment_status, OrderFulfillmentStatus.COMPLETED)
            self.assertIsNotNone(refreshed.fulfilled_at)

    def test_admin_orders_bulk_status_completed_sets_fulfillment(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=102, telegram_user_id=700702)
            first = Order(
                id=202,
                user_id=102,
                tariff=Tariff.T1,
                amount=990,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                fulfillment_status=OrderFulfillmentStatus.PENDING,
            )
            second = Order(
                id=203,
                user_id=102,
                tariff=Tariff.T2,
                amount=1990,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                fulfillment_status=OrderFulfillmentStatus.PENDING,
            )
            session.add_all([user, first, second])
            session.commit()

        response = self.client.post(
            "/admin/api/orders/bulk-status",
            json={"ids": [202, 203], "status": "completed"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["updated"], 2)

        with self.SessionLocal() as session:
            refreshed = session.query(Order).filter(Order.id.in_([202, 203])).all()
            self.assertEqual(len(refreshed), 2)
            for order in refreshed:
                self.assertEqual(order.fulfillment_status, OrderFulfillmentStatus.COMPLETED)
                self.assertIsNotNone(order.fulfilled_at)

    def test_admin_orders_bulk_delete_removes_selected_orders(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=103, telegram_user_id=700703)
            first = Order(
                id=204,
                user_id=103,
                tariff=Tariff.T1,
                amount=990,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.CREATED,
                fulfillment_status=OrderFulfillmentStatus.PENDING,
            )
            second = Order(
                id=205,
                user_id=103,
                tariff=Tariff.T2,
                amount=1990,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                fulfillment_status=OrderFulfillmentStatus.PENDING,
            )
            session.add_all([user, first, second])
            session.commit()

        response = self.client.post(
            "/admin/api/orders/bulk-delete",
            json={"ids": [204]},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["deleted"], 1)

        with self.SessionLocal() as session:
            self.assertIsNone(session.get(Order, 204))
            self.assertIsNotNone(session.get(Order, 205))


if __name__ == "__main__":
    unittest.main()
