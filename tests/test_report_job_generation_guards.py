import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import report_service as report_service_module
from app.db.base import Base
from app.db.models import (
    Order,
    OrderFulfillmentStatus,
    OrderStatus,
    PaymentProvider,
    ReportJob,
    ReportJobStatus,
    ScreenStateRecord,
    Tariff,
    User,
    UserProfile,
)


class ReportJobGenerationGuardsTests(unittest.IsolatedAsyncioTestCase):
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

    def tearDown(self) -> None:
        report_service_module.get_session = self._old_get_session
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    async def test_paid_job_fails_without_profile(self) -> None:
        with self.SessionLocal() as session:
            session.add(User(id=1, telegram_user_id=101, telegram_username="user"))
            session.add(
                Order(
                    id=1,
                    user_id=1,
                    tariff=Tariff.T1,
                    amount=560,
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PAID,
                    fulfillment_status=OrderFulfillmentStatus.PENDING,
                )
            )
            session.add(
                ScreenStateRecord(
                    telegram_user_id=101,
                    data={"selected_tariff": Tariff.T1.value, "order_id": "1"},
                )
            )
            session.add(
                ReportJob(
                    id=1,
                    user_id=1,
                    order_id=1,
                    tariff=Tariff.T1,
                    status=ReportJobStatus.PENDING,
                    attempts=0,
                    chat_id=101,
                )
            )
            session.commit()

        with patch.object(report_service_module.report_service, "generate_report", new=AsyncMock(return_value=None)) as mocked:
            result = await report_service_module.report_service.generate_report_by_job(job_id=1)

        self.assertIsNone(result)
        mocked.assert_not_awaited()
        with self.SessionLocal() as session:
            job = session.get(ReportJob, 1)
            self.assertEqual(job.status, ReportJobStatus.FAILED)
            self.assertEqual(job.last_error, "profile_missing")

    async def test_paid_job_fails_on_amount_mismatch(self) -> None:
        with self.SessionLocal() as session:
            session.add(User(id=1, telegram_user_id=202, telegram_username="user"))
            session.add(
                UserProfile(
                    user_id=1,
                    name="Name",
                    gender="x",
                    birth_date="01.01.2000",
                    birth_time="00.00",
                    birth_place_city="City",
                    birth_place_region="Region",
                    birth_place_country="Country",
                )
            )
            session.add(
                Order(
                    id=2,
                    user_id=1,
                    tariff=Tariff.T1,
                    amount=1,
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PAID,
                    fulfillment_status=OrderFulfillmentStatus.PENDING,
                )
            )
            session.add(
                ScreenStateRecord(
                    telegram_user_id=202,
                    data={"selected_tariff": Tariff.T1.value, "order_id": "2"},
                )
            )
            session.add(
                ReportJob(
                    id=2,
                    user_id=1,
                    order_id=2,
                    tariff=Tariff.T1,
                    status=ReportJobStatus.PENDING,
                    attempts=0,
                    chat_id=202,
                )
            )
            session.commit()

        with patch.object(report_service_module.report_service, "generate_report", new=AsyncMock(return_value=None)) as mocked:
            result = await report_service_module.report_service.generate_report_by_job(job_id=2)

        self.assertIsNone(result)
        mocked.assert_not_awaited()
        with self.SessionLocal() as session:
            job = session.get(ReportJob, 2)
            self.assertEqual(job.status, ReportJobStatus.FAILED)
            self.assertEqual(job.last_error, "paid_order_amount_mismatch")


if __name__ == "__main__":
    unittest.main()
