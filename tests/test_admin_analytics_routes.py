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
    PaymentConfirmationSource,
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


    def test_orders_endpoint_supports_user_and_payment_confirmed_filters(self) -> None:
        with self.SessionLocal() as session:
            user_a = User(id=140, telegram_user_id=700740)
            user_b = User(id=141, telegram_user_id=700741)
            session.add_all([user_a, user_b])
            session.flush()
            session.add_all(
                [
                    Order(
                        user_id=140,
                        tariff=Tariff.T1,
                        amount=1000,
                        currency="RUB",
                        provider=PaymentProvider.PRODAMUS,
                        status=OrderStatus.PAID,
                        payment_confirmed=True,
                        payment_confirmation_source=PaymentConfirmationSource.PROVIDER_WEBHOOK,
                        payment_confirmed_at=datetime.now(timezone.utc),
                    ),
                    Order(
                        user_id=140,
                        tariff=Tariff.T2,
                        amount=2000,
                        currency="RUB",
                        provider=PaymentProvider.PRODAMUS,
                        status=OrderStatus.PAID,
                        payment_confirmed=False,
                        payment_confirmation_source=PaymentConfirmationSource.ADMIN_MANUAL,
                    ),
                    Order(
                        user_id=141,
                        tariff=Tariff.T3,
                        amount=3000,
                        currency="RUB",
                        provider=PaymentProvider.PRODAMUS,
                        status=OrderStatus.PAID,
                        payment_confirmed=True,
                        payment_confirmation_source=PaymentConfirmationSource.PROVIDER_POLL,
                        payment_confirmed_at=datetime.now(timezone.utc),
                    ),
                ]
            )
            session.commit()

        response = self.client.get(
            "/admin/api/orders",
            params={"user_id": 140, "payment_confirmed": True},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["orders"]), 1)
        self.assertEqual(payload["orders"][0]["user_id"], 140)
        self.assertTrue(payload["orders"][0]["payment_confirmed"])

    def test_users_payload_includes_confirmed_order_aggregates_and_sorting(self) -> None:
        with self.SessionLocal() as session:
            user_a = User(id=130, telegram_user_id=700730)
            user_b = User(id=131, telegram_user_id=700731)
            session.add_all([user_a, user_b])
            session.flush()
            session.add_all(
                [
                    Order(
                        user_id=130,
                        tariff=Tariff.T1,
                        amount=1000,
                        currency="RUB",
                        provider=PaymentProvider.PRODAMUS,
                        status=OrderStatus.PAID,
                        payment_confirmed=True,
                        payment_confirmation_source=PaymentConfirmationSource.PROVIDER_WEBHOOK,
                        payment_confirmed_at=datetime.now(timezone.utc),
                    ),
                    Order(
                        user_id=130,
                        tariff=Tariff.T2,
                        amount=2000,
                        currency="RUB",
                        provider=PaymentProvider.PRODAMUS,
                        status=OrderStatus.PAID,
                        payment_confirmed=True,
                        payment_confirmation_source=PaymentConfirmationSource.ADMIN_MANUAL,
                        payment_confirmed_at=datetime.now(timezone.utc),
                    ),
                    Order(
                        user_id=130,
                        tariff=Tariff.T3,
                        amount=9999,
                        currency="RUB",
                        provider=PaymentProvider.PRODAMUS,
                        status=OrderStatus.PAID,
                        payment_confirmed=False,
                        payment_confirmation_source=PaymentConfirmationSource.ADMIN_MANUAL,
                        payment_confirmed_at=datetime.now(timezone.utc),
                    ),
                    Order(
                        user_id=131,
                        tariff=Tariff.T1,
                        amount=500,
                        currency="RUB",
                        provider=PaymentProvider.PRODAMUS,
                        status=OrderStatus.PAID,
                        payment_confirmed=True,
                        payment_confirmation_source=PaymentConfirmationSource.PROVIDER_WEBHOOK,
                        payment_confirmed_at=datetime.now(timezone.utc),
                    ),
                ]
            )
            session.commit()

        response = self.client.get(
            "/admin/api/users",
            params={"sort_by": "confirmed_revenue_total", "sort_dir": "desc"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("users", payload)
        self.assertGreaterEqual(len(payload["users"]), 2)

        first = payload["users"][0]
        second = payload["users"][1]

        self.assertEqual(first["id"], 130)
        self.assertEqual(first["confirmed_orders_count"], 2)
        self.assertEqual(first["confirmed_revenue_total"], 3000.0)
        self.assertEqual(first["manual_paid_orders_count"], 1)
        self.assertEqual(second["id"], 131)

    def test_overview_financial_kpi_split_provider_confirmed_and_manual(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=110, telegram_user_id=700710)
            provider_confirmed = Order(
                id=210,
                user_id=110,
                tariff=Tariff.T1,
                amount=1000,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                payment_confirmed=True,
                payment_confirmation_source=PaymentConfirmationSource.PROVIDER_WEBHOOK,
                payment_confirmed_at=datetime.now(timezone.utc),
            )
            provider_confirmed_by_source = Order(
                id=211,
                user_id=110,
                tariff=Tariff.T2,
                amount=2000,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                payment_confirmed=False,
                payment_confirmation_source=PaymentConfirmationSource.PROVIDER_POLL,
                payment_confirmed_at=datetime.now(timezone.utc),
            )
            manual_paid = Order(
                id=212,
                user_id=110,
                tariff=Tariff.T3,
                amount=3000,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                payment_confirmed=True,
                payment_confirmation_source=PaymentConfirmationSource.ADMIN_MANUAL,
                payment_confirmed_at=datetime.now(timezone.utc),
            )
            session.add_all([user, provider_confirmed, provider_confirmed_by_source, manual_paid])
            session.commit()

        response = self.client.get("/admin/api/overview")
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["confirmed_paid_orders"], 2)
        self.assertEqual(payload["confirmed_revenue_total"], 3000.0)
        self.assertEqual(payload["manual_paid_orders"], 1)
        self.assertEqual(payload["manual_paid_amount_total"], 3000.0)
        self.assertEqual(payload["arpu_confirmed"], 1500.0)

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


    def test_reports_payload_includes_order_payment_fields_and_financial_basis(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=120, telegram_user_id=700720)
            provider_order = Order(
                id=220,
                user_id=120,
                tariff=Tariff.T1,
                amount=1000,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                payment_confirmed=True,
                payment_confirmation_source=PaymentConfirmationSource.PROVIDER_WEBHOOK,
                payment_confirmed_at=datetime.now(timezone.utc),
            )
            manual_order = Order(
                id=221,
                user_id=120,
                tariff=Tariff.T2,
                amount=2000,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                payment_confirmed=True,
                payment_confirmation_source=PaymentConfirmationSource.ADMIN_MANUAL,
            )
            unpaid_order = Order(
                id=222,
                user_id=120,
                tariff=Tariff.T3,
                amount=3000,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PENDING,
                payment_confirmed=False,
            )
            reports = [
                Report(id=320, user_id=120, order_id=220, tariff=Tariff.T1, report_text="provider"),
                Report(id=321, user_id=120, order_id=221, tariff=Tariff.T2, report_text="manual"),
                Report(id=322, user_id=120, order_id=222, tariff=Tariff.T3, report_text="none"),
            ]
            session.add_all([user, provider_order, manual_order, unpaid_order, *reports])
            session.commit()

        response = self.client.get("/admin/api/reports")
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        provider_row = next(item for item in payload["reports"] if item["id"] == 320)
        self.assertEqual(provider_row["order_status"], OrderStatus.PAID.value)
        self.assertTrue(provider_row["payment_confirmed"])
        self.assertEqual(provider_row["payment_confirmation_source"], PaymentConfirmationSource.PROVIDER_WEBHOOK.value)
        self.assertIsNotNone(provider_row["payment_confirmed_at"])
        self.assertEqual(provider_row["financial_basis"], "provider_confirmed")

        manual_row = next(item for item in payload["reports"] if item["id"] == 321)
        self.assertEqual(manual_row["financial_basis"], "manual")

        unpaid_row = next(item for item in payload["reports"] if item["id"] == 322)
        self.assertEqual(unpaid_row["financial_basis"], "none")
        self.assertFalse(unpaid_row["payment_confirmed"])


    def test_reports_api_supports_financial_basis_filter(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=121, telegram_user_id=700721)
            provider_order = Order(
                id=223,
                user_id=121,
                tariff=Tariff.T1,
                amount=1000,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                payment_confirmed=True,
                payment_confirmation_source=PaymentConfirmationSource.PROVIDER_WEBHOOK,
            )
            manual_order = Order(
                id=224,
                user_id=121,
                tariff=Tariff.T2,
                amount=2000,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                payment_confirmed=True,
                payment_confirmation_source=PaymentConfirmationSource.ADMIN_MANUAL,
            )
            session.add_all(
                [
                    user,
                    provider_order,
                    manual_order,
                    Report(id=323, user_id=121, order_id=223, tariff=Tariff.T1, report_text="provider"),
                    Report(id=324, user_id=121, order_id=224, tariff=Tariff.T2, report_text="manual"),
                ]
            )
            session.commit()

        response = self.client.get("/admin/api/reports", params={"financial_basis": "provider_confirmed"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["reports"]), 1)
        self.assertEqual(payload["reports"][0]["financial_basis"], "provider_confirmed")

    def test_reports_api_supports_payment_not_confirmed_filter(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=122, telegram_user_id=700722)
            confirmed_order = Order(
                id=225,
                user_id=122,
                tariff=Tariff.T1,
                amount=1000,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                payment_confirmed=True,
                payment_confirmation_source=PaymentConfirmationSource.PROVIDER_WEBHOOK,
            )
            pending_order = Order(
                id=226,
                user_id=122,
                tariff=Tariff.T2,
                amount=2000,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PENDING,
                payment_confirmed=False,
            )
            session.add_all(
                [
                    user,
                    confirmed_order,
                    pending_order,
                    Report(id=325, user_id=122, order_id=225, tariff=Tariff.T1, report_text="ok"),
                    Report(id=326, user_id=122, order_id=226, tariff=Tariff.T2, report_text="warn"),
                ]
            )
            session.commit()

        response = self.client.get("/admin/api/reports", params={"payment_not_confirmed_only": "true"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["reports"]), 1)
        self.assertEqual(payload["reports"][0]["id"], 326)
        self.assertFalse(payload["reports"][0]["payment_confirmed"])

    def test_admin_ui_contains_reports_financial_filter_and_alert_container(self) -> None:
        with patch.object(admin_routes, "_admin_credentials_ready", return_value=True), patch.object(
            admin_routes,
            "_admin_session_token",
            return_value="token",
        ):
            response = self.client.get("/admin", cookies={"admin_session": "token"})

        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("reportsFilterProviderConfirmed", html)
        self.assertIn("reportsFilterPaymentNotConfirmed", html)
        self.assertIn("reportsAlerts", html)
        self.assertIn("showProblemReportsFromAlert", html)
        self.assertIn("Фин. основание", html)
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

    def test_admin_order_status_paid_marks_manual_source_without_payment_confirmation(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=104, telegram_user_id=700704)
            order = Order(
                id=206,
                user_id=104,
                tariff=Tariff.T1,
                amount=990,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.CREATED,
            )
            session.add_all([user, order])
            session.commit()

        response = self.client.post("/admin/api/orders/206/status", json={"status": "paid"})
        self.assertEqual(response.status_code, 200)

        with self.SessionLocal() as session:
            refreshed = session.get(Order, 206)
            self.assertIsNotNone(refreshed)
            self.assertEqual(refreshed.status, OrderStatus.PAID)
            self.assertEqual(
                refreshed.payment_confirmation_source,
                PaymentConfirmationSource.ADMIN_MANUAL,
            )
            self.assertFalse(refreshed.payment_confirmed)
            self.assertIsNone(refreshed.payment_confirmed_at)

    def test_admin_orders_bulk_status_paid_marks_manual_source_without_payment_confirmation(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=105, telegram_user_id=700705)
            first = Order(
                id=207,
                user_id=105,
                tariff=Tariff.T1,
                amount=990,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.CREATED,
            )
            second = Order(
                id=208,
                user_id=105,
                tariff=Tariff.T2,
                amount=1990,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PENDING,
            )
            session.add_all([user, first, second])
            session.commit()

        response = self.client.post(
            "/admin/api/orders/bulk-status",
            json={"ids": [207, 208], "status": "paid"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated"], 2)

        with self.SessionLocal() as session:
            refreshed = session.query(Order).filter(Order.id.in_([207, 208])).all()
            self.assertEqual(len(refreshed), 2)
            for order in refreshed:
                self.assertEqual(order.status, OrderStatus.PAID)
                self.assertEqual(
                    order.payment_confirmation_source,
                    PaymentConfirmationSource.ADMIN_MANUAL,
                )
                self.assertFalse(order.payment_confirmed)
                self.assertIsNone(order.payment_confirmed_at)

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
