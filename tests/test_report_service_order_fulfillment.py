import unittest
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import report_service as report_service_module
from app.core.llm_router import LLMResponse
from app.db.base import Base
from app.db.models import (
    Order,
    OrderFulfillmentStatus,
    OrderStatus,
    PaymentProvider,
    Report,
    Tariff,
    User,
)


class ReportServiceOrderFulfillmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

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

        self._old_get_session = report_service_module.get_session
        report_service_module.get_session = _test_get_session

        with self.SessionLocal() as session:
            session.add(User(id=1, telegram_user_id=101010, telegram_username="tester"))
            session.add(
                Order(
                    id=10,
                    user_id=1,
                    tariff=Tariff.T1,
                    amount=990,
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PAID,
                    fulfillment_status=OrderFulfillmentStatus.PENDING,
                )
            )
            session.commit()

    def tearDown(self) -> None:
        report_service_module.get_session = self._old_get_session
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_persist_report_marks_order_as_completed(self) -> None:
        report_service_module.report_service._persist_report(
            user_id=1,
            state={"selected_tariff": Tariff.T1.value, "order_id": "10"},
            response=LLMResponse(text="готово", provider="gemini", model="flash"),
            safety_flags={},
        )

        with self.SessionLocal() as session:
            order = session.get(Order, 10)
            self.assertIsNotNone(order)
            self.assertEqual(order.fulfillment_status, OrderFulfillmentStatus.COMPLETED)
            self.assertIsNotNone(order.fulfilled_at)
            self.assertIsNotNone(order.fulfilled_report_id)

    def test_persist_report_handles_unique_conflict_for_order(self) -> None:
        with self.SessionLocal() as session:
            session.add(
                Report(
                    user_id=1,
                    order_id=10,
                    tariff=Tariff.T1,
                    report_text="already-exists",
                    report_text_canonical="already-exists",
                )
            )
            session.commit()

        report_service_module.report_service._persist_report(
            user_id=1,
            state={"selected_tariff": Tariff.T1.value, "order_id": "10"},
            response=LLMResponse(text="новый", provider="gemini", model="flash"),
            safety_flags={},
        )

        with self.SessionLocal() as session:
            reports_count = (
                session.query(Report)
                .filter(Report.order_id == 10)
                .count()
            )
            self.assertEqual(reports_count, 1)


if __name__ == "__main__":
    unittest.main()
