import json
import unittest
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import webhooks as webhook_routes
from app.db.base import Base
from app.db.models import Order, OrderStatus, PaymentProvider, Tariff, User
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


if __name__ == "__main__":
    unittest.main()
