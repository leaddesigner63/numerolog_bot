import json
import unittest
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import webhooks as webhook_routes
from app.db.base import Base
from app.db.models import (
    Order,
    OrderStatus,
    PaymentConfirmationSource,
    PaymentProvider,
    Tariff,
    User,
)
from app.main import create_app
from app.payments.base import WebhookResult


class _ProviderStub:
    def __init__(self, result: WebhookResult) -> None:
        self.provider = PaymentProvider.PRODAMUS
        self._result = result

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> WebhookResult:
        return self._result


class PaymentWebhookRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.app = create_app()

        @contextmanager
        def _test_get_session():
            session = self.SessionLocal()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        self._old_get_session = webhook_routes.get_session
        webhook_routes.get_session = _test_get_session

        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        webhook_routes.get_session = self._old_get_session
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _seed_order(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=1, telegram_user_id=123456)
            order = Order(
                id=1001,
                user_id=1,
                tariff=Tariff.T1,
                amount=990.00,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.CREATED,
            )
            session.add(user)
            session.add(order)
            session.commit()

    def test_paid_webhook_is_idempotent_on_repeat_delivery(self) -> None:
        self._seed_order()
        provider_stub = _ProviderStub(
            WebhookResult(order_id=1001, provider_payment_id="pay-1", is_paid=True)
        )
        self.app.dependency_overrides.clear()

        original = webhook_routes.get_payment_provider
        webhook_routes.get_payment_provider = lambda provider_name=None: provider_stub
        try:
            payload = json.dumps({"order_id": "1001", "status": "paid"}).encode("utf-8")
            first_response = self.client.post("/webhooks/payments", content=payload)
            second_response = self.client.post("/webhooks/payments", content=payload)
        finally:
            webhook_routes.get_payment_provider = original

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)

        with self.SessionLocal() as session:
            order = session.get(Order, 1001)
            self.assertIsNotNone(order)
            assert order is not None
            self.assertEqual(order.status, OrderStatus.PAID)
            self.assertEqual(order.provider_payment_id, "pay-1")
            self.assertIsNotNone(order.paid_at)
            self.assertTrue(order.payment_confirmed)
            self.assertIsNotNone(order.payment_confirmed_at)
            self.assertEqual(
                order.payment_confirmation_source,
                PaymentConfirmationSource.PROVIDER_WEBHOOK,
            )

    def test_paid_webhook_sets_payment_confirmation_fields(self) -> None:
        self._seed_order()
        provider_stub = _ProviderStub(
            WebhookResult(order_id=1001, provider_payment_id="pay-777", is_paid=True)
        )
        original = webhook_routes.get_payment_provider
        webhook_routes.get_payment_provider = lambda provider_name=None: provider_stub
        try:
            payload = json.dumps({"order_id": "1001", "status": "paid"}).encode("utf-8")
            response = self.client.post("/webhooks/payments", content=payload)
        finally:
            webhook_routes.get_payment_provider = original

        self.assertEqual(response.status_code, 200)
        with self.SessionLocal() as session:
            order = session.get(Order, 1001)
            self.assertIsNotNone(order)
            assert order is not None
            self.assertTrue(order.payment_confirmed)
            self.assertEqual(order.payment_confirmation_source, PaymentConfirmationSource.PROVIDER_WEBHOOK)
            self.assertIsNotNone(order.payment_confirmed_at)

    def test_paid_webhook_repeat_delivery_is_idempotent_for_confirmation_metadata(self) -> None:
        self._seed_order()
        first_provider_stub = _ProviderStub(
            WebhookResult(order_id=1001, provider_payment_id="pay-first", is_paid=True)
        )
        second_provider_stub = _ProviderStub(
            WebhookResult(order_id=1001, provider_payment_id="pay-second", is_paid=True)
        )
        original = webhook_routes.get_payment_provider
        try:
            webhook_routes.get_payment_provider = lambda provider_name=None: first_provider_stub
            payload = json.dumps({"order_id": "1001", "status": "paid"}).encode("utf-8")
            first_response = self.client.post("/webhooks/payments", content=payload)
            self.assertEqual(first_response.status_code, 200)
            with self.SessionLocal() as session:
                saved_after_first = session.get(Order, 1001)
                self.assertIsNotNone(saved_after_first)
                assert saved_after_first is not None
                first_confirmed_at = saved_after_first.payment_confirmed_at
                self.assertIsNotNone(first_confirmed_at)

            webhook_routes.get_payment_provider = lambda provider_name=None: second_provider_stub
            second_response = self.client.post("/webhooks/payments", content=payload)
            self.assertEqual(second_response.status_code, 200)
        finally:
            webhook_routes.get_payment_provider = original

        with self.SessionLocal() as session:
            order = session.get(Order, 1001)
            self.assertIsNotNone(order)
            assert order is not None
            self.assertEqual(order.provider_payment_id, "pay-first")
            self.assertEqual(order.payment_confirmed_at, first_confirmed_at)
            self.assertTrue(order.payment_confirmed)
            self.assertEqual(order.payment_confirmation_source, PaymentConfirmationSource.PROVIDER_WEBHOOK)

    def test_prodamus_probe_with_sign_test_returns_ok(self) -> None:
        response = self.client.post(
            "/webhooks/payments?provider=prodamus",
            data="a=1",
            headers={"Sign": "test", "Content-Type": "application/x-www-form-urlencoded"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


    def test_payload_fingerprint_and_signature_source_helpers(self) -> None:
        fingerprint = webhook_routes._payload_fingerprint(b'{"order_id":"1001"}')
        self.assertEqual(len(fingerprint), 12)

        source_header = webhook_routes._signature_source({"sign": "abc"}, {"order_id": "1"})
        self.assertEqual(source_header, "header:sign")

        source_payload = webhook_routes._signature_source({}, {"order_id": "1", "sign": "abc"})
        self.assertEqual(source_payload, "payload:sign")

        source_missing = webhook_routes._signature_source({}, {"order_id": "1"})
        self.assertEqual(source_missing, "missing")


if __name__ == "__main__":
    unittest.main()
