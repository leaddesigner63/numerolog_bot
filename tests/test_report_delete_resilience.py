import unittest
from unittest.mock import Mock, patch

from app.bot.handlers import screens
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Order, OrderFulfillmentStatus, OrderStatus, PaymentProvider, Report, Tariff, User


class ReportDeleteResilienceTests(unittest.TestCase):
    def test_delete_report_with_assets_keeps_flow_on_pdf_delete_error(self) -> None:
        session = Mock()
        report = Report(id=123)
        report.pdf_storage_key = "broken-key"

        with patch.object(
            screens.pdf_service,
            "delete_pdf",
            side_effect=RuntimeError("storage unavailable"),
        ):
            deleted = screens._delete_report_with_assets(session, report)

        self.assertTrue(deleted)
        session.delete.assert_called_once_with(report)

    def test_delete_report_with_assets_returns_false_when_db_delete_fails(self) -> None:
        session = Mock()
        session.delete.side_effect = RuntimeError("db error")
        report = Report(id=7)
        report.pdf_storage_key = None

        with patch.object(screens.pdf_service, "delete_pdf"):
            deleted = screens._delete_report_with_assets(session, report)

        self.assertFalse(deleted)

    def test_delete_report_with_assets_clears_fulfilled_report_link_for_orders(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SessionLocal = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)

        try:
            with SessionLocal() as session:
                user = User(id=1, telegram_user_id=1001)
                session.add(user)
                session.flush()
                report = Report(user_id=user.id, tariff=Tariff.T1, report_text="Тест")
                session.add(report)
                session.flush()
                order = Order(
                    user_id=user.id,
                    tariff=Tariff.T1,
                    amount=560,
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PAID,
                    fulfillment_status=OrderFulfillmentStatus.COMPLETED,
                    fulfilled_report_id=report.id,
                )
                session.add(order)
                session.commit()

            with SessionLocal() as session:
                report = session.execute(select(Report).limit(1)).scalar_one()
                deleted = screens._delete_report_with_assets(session, report)
                session.commit()
                refreshed_order = session.execute(select(Order).limit(1)).scalar_one()

            self.assertTrue(deleted)
            self.assertIsNone(refreshed_order.fulfilled_report_id)
            self.assertEqual(refreshed_order.fulfillment_status, OrderFulfillmentStatus.PENDING)
        finally:
            Base.metadata.drop_all(engine)
            engine.dispose()



if __name__ == "__main__":
    unittest.main()
