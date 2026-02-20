import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import report_service as report_service_module
from app.db.base import Base
from app.db.models import Report, ReportJob, ReportJobStatus, ScreenStateRecord, Tariff, User, UserProfile


class ReportJobTariffPriorityTests(unittest.IsolatedAsyncioTestCase):
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
            session.add(User(id=1, telegram_user_id=4242, telegram_username="tester"))
            session.add(
                UserProfile(
                    user_id=1,
                    name="Tester",
                    gender="x",
                    birth_date="01.01.2000",
                    birth_time="00.00",
                    birth_place_city="City",
                    birth_place_region="Region",
                    birth_place_country="Country",
                )
            )
            session.add(
                ScreenStateRecord(
                    telegram_user_id=4242,
                    data={"selected_tariff": Tariff.T3.value, "order_id": "999"},
                )
            )
            session.add(
                ReportJob(
                    id=1,
                    user_id=1,
                    order_id=None,
                    tariff=Tariff.T0,
                    status=ReportJobStatus.PENDING,
                    attempts=0,
                    chat_id=4242,
                )
            )
            session.commit()

    def tearDown(self) -> None:
        report_service_module.get_session = self._old_get_session
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    async def test_generate_report_by_job_uses_job_tariff_not_stale_screen_state(self) -> None:
        with patch.object(
            report_service_module.report_service,
            "generate_report",
            new=AsyncMock(return_value=None),
        ) as generate_report:
            await report_service_module.report_service.generate_report_by_job(job_id=1)

        generate_report.assert_awaited_once()
        called_state = generate_report.await_args.kwargs["state"]
        self.assertEqual(called_state.get("selected_tariff"), Tariff.T0.value)
        self.assertNotIn("order_id", called_state)


    async def test_generate_report_by_job_t0_with_stale_order_id_uses_tariff_lookup(self) -> None:
        with self.SessionLocal() as session:
            session.add(
                ReportJob(
                    id=2,
                    user_id=1,
                    order_id=999,
                    tariff=Tariff.T0,
                    status=ReportJobStatus.PENDING,
                    attempts=0,
                    chat_id=4242,
                )
            )
            session.add(
                Report(
                    user_id=1,
                    order_id=None,
                    tariff=Tariff.T0,
                    report_text="t0 отчет",
                    safety_flags={},
                )
            )
            session.commit()

        with patch.object(
            report_service_module.report_service,
            "generate_report",
            new=AsyncMock(return_value=report_service_module.LLMResponse(text="ok", provider="gemini", model="flash")),
        ):
            result = await report_service_module.report_service.generate_report_by_job(job_id=2)

        self.assertIsNotNone(result)
        self.assertEqual(result.report_text, "t0 отчет")
        with self.SessionLocal() as session:
            job = session.get(ReportJob, 2)
            self.assertIsNotNone(job)
            self.assertEqual(job.status, ReportJobStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
