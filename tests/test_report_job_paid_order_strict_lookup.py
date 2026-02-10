import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

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
    ReportJob,
    ReportJobStatus,
    ScreenStateRecord,
    Tariff,
    User,
)


class ReportJobPaidOrderStrictLookupTests(unittest.IsolatedAsyncioTestCase):
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
            session.add(User(id=1, telegram_user_id=777, telegram_username="tester"))
            session.add(
                ScreenStateRecord(
                    telegram_user_id=777,
                    data={"selected_tariff": Tariff.T1.value, "order_id": "10"},
                )
            )
            session.add(
                Order(
                    id=9,
                    user_id=1,
                    tariff=Tariff.T1,
                    amount=990,
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PAID,
                    fulfillment_status=OrderFulfillmentStatus.COMPLETED,
                )
            )
            session.add(
                Report(
                    user_id=1,
                    order_id=9,
                    tariff=Tariff.T1,
                    report_text="старый отчет",
                    safety_flags={},
                )
            )
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
            session.add(
                ReportJob(
                    id=1,
                    user_id=1,
                    order_id=10,
                    tariff=Tariff.T1,
                    status=ReportJobStatus.PENDING,
                    attempts=0,
                    chat_id=777,
                )
            )
            session.commit()

    def tearDown(self) -> None:
        report_service_module.get_session = self._old_get_session
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    async def test_generate_report_by_job_does_not_fallback_to_old_report_for_new_paid_order(self) -> None:
        with patch.object(
            report_service_module.report_service,
            "generate_report",
            new=AsyncMock(
                return_value=LLMResponse(text="новый отчет", provider="gemini", model="flash")
            ),
        ):
            result = await report_service_module.report_service.generate_report_by_job(job_id=1)

        self.assertIsNone(result)
        with self.SessionLocal() as session:
            job = session.get(ReportJob, 1)
            self.assertIsNotNone(job)
            self.assertEqual(job.status, ReportJobStatus.FAILED)
            self.assertEqual(job.last_error, "report_not_saved_for_order")


if __name__ == "__main__":
    unittest.main()
