import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.handlers.screens import _create_report_job
from app.db.base import Base
from app.db.models import (
    Order,
    OrderFulfillmentStatus,
    OrderStatus,
    PaymentProvider,
    ReportJob,
    Tariff,
    User,
)


class ReportJobRequiresPaidOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

        with self.SessionLocal() as session:
            session.add(User(id=1, telegram_user_id=1001, telegram_username="user1"))
            session.add(User(id=2, telegram_user_id=1002, telegram_username="user2"))
            session.add(
                Order(
                    id=10,
                    user_id=1,
                    tariff=Tariff.T1,
                    amount=990,
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PENDING,
                    fulfillment_status=OrderFulfillmentStatus.PENDING,
                )
            )
            session.add(
                Order(
                    id=11,
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
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_create_report_job_rejects_unpaid_order_for_paid_tariff(self) -> None:
        with self.SessionLocal() as session:
            user = session.get(User, 1)
            with patch("app.bot.handlers.screens.screen_manager.update_state"):
                job = _create_report_job(
                    session,
                    user=user,
                    tariff_value=Tariff.T1.value,
                    order_id=10,
                    chat_id=1001,
                )
            session.commit()

            self.assertIsNone(job)
            self.assertEqual(session.query(ReportJob).count(), 0)

    def test_create_report_job_rejects_foreign_order_for_paid_tariff(self) -> None:
        with self.SessionLocal() as session:
            user = session.get(User, 2)
            with patch("app.bot.handlers.screens.screen_manager.update_state"):
                job = _create_report_job(
                    session,
                    user=user,
                    tariff_value=Tariff.T1.value,
                    order_id=11,
                    chat_id=1002,
                )
            session.commit()

            self.assertIsNone(job)
            self.assertEqual(session.query(ReportJob).count(), 0)

    def test_create_report_job_creates_job_for_paid_matching_order(self) -> None:
        with self.SessionLocal() as session:
            user = session.get(User, 1)
            with patch("app.bot.handlers.screens.screen_manager.update_state"):
                job = _create_report_job(
                    session,
                    user=user,
                    tariff_value=Tariff.T1.value,
                    order_id=11,
                    chat_id=1001,
                )
            session.commit()

            self.assertIsNotNone(job)
            self.assertEqual(session.query(ReportJob).count(), 1)


if __name__ == "__main__":
    unittest.main()
