import unittest
from contextlib import contextmanager
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import report_service as report_service_module
from app.core.config import settings
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
                    amount=settings.tariff_prices_rub[Tariff.T1.value],
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

    def test_resolve_paid_order_id_returns_none_for_owner_mismatch(self) -> None:
        with self.SessionLocal() as session:
            session.add(
                Order(
                    id=11,
                    user_id=2,
                    tariff=Tariff.T1,
                    amount=settings.tariff_prices_rub[Tariff.T1.value],
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PAID,
                    fulfillment_status=OrderFulfillmentStatus.PENDING,
                )
            )
            session.commit()
            with patch.object(report_service_module.report_service._logger, "warning") as warning_mock:
                resolved_order_id = report_service_module.report_service._resolve_paid_order_id(
                    session,
                    {"selected_tariff": Tariff.T1.value, "order_id": "11"},
                    user_id=1,
                )

        self.assertIsNone(resolved_order_id)
        warning_mock.assert_any_call(
            "order_owner_mismatch",
            extra={"user_id": 1, "order_id": 11, "order_user_id": 2},
        )

    def test_resolve_paid_order_id_returns_none_for_tariff_mismatch(self) -> None:
        with self.SessionLocal() as session:
            session.add(
                Order(
                    id=12,
                    user_id=1,
                    tariff=Tariff.T2,
                    amount=settings.tariff_prices_rub[Tariff.T2.value],
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PAID,
                    fulfillment_status=OrderFulfillmentStatus.PENDING,
                )
            )
            session.commit()
            with patch.object(report_service_module.report_service._logger, "warning") as warning_mock:
                resolved_order_id = report_service_module.report_service._resolve_paid_order_id(
                    session,
                    {"selected_tariff": Tariff.T1.value, "order_id": "12"},
                    user_id=1,
                )

        self.assertIsNone(resolved_order_id)
        warning_mock.assert_any_call(
            "order_tariff_mismatch",
            extra={
                "user_id": 1,
                "order_id": 12,
                "order_tariff": Tariff.T2.value,
                "selected_tariff": Tariff.T1.value,
            },
        )

    def test_resolve_paid_order_id_returns_none_for_amount_mismatch(self) -> None:
        with self.SessionLocal() as session:
            session.add(
                Order(
                    id=13,
                    user_id=1,
                    tariff=Tariff.T1,
                    amount=settings.tariff_prices_rub[Tariff.T1.value] + 1,
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PAID,
                    fulfillment_status=OrderFulfillmentStatus.PENDING,
                )
            )
            session.commit()
            with patch.object(report_service_module.report_service._logger, "warning") as warning_mock:
                resolved_order_id = report_service_module.report_service._resolve_paid_order_id(
                    session,
                    {"selected_tariff": Tariff.T1.value, "order_id": "13"},
                    user_id=1,
                )

        self.assertIsNone(resolved_order_id)
        warning_mock.assert_any_call(
            "order_amount_mismatch",
            extra={
                "user_id": 1,
                "order_id": 13,
                "order_amount": float(settings.tariff_prices_rub[Tariff.T1.value] + 1),
                "expected_amount": float(settings.tariff_prices_rub[Tariff.T1.value]),
            },
        )


    def test_persist_report_does_not_force_store_paid_tariff_without_order(self) -> None:
        with self.assertRaises(report_service_module.ReportPersistenceBlockedError) as exc:
            report_service_module.report_service._persist_report(
                user_id=1,
                state={"selected_tariff": Tariff.T1.value},
                response=LLMResponse(text="fallback", provider="safety_fallback", model="template"),
                safety_flags={},
                force_store=True,
            )

        self.assertEqual(str(exc.exception), "paid_force_store_invalid_order")
        with self.SessionLocal() as session:
            reports_count = session.query(Report).count()
            self.assertEqual(reports_count, 0)



if __name__ == "__main__":
    unittest.main()
