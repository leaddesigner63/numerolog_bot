import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot import report_jobs_worker as report_jobs_worker_module
from app.db.base import Base
from app.db.models import ReportJob, ReportJobStatus, ServiceHeartbeat, Tariff, User


class ReportJobsWorkerHeartbeatTests(unittest.IsolatedAsyncioTestCase):
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

        self._old_get_session = report_jobs_worker_module.get_session
        report_jobs_worker_module.get_session = _test_get_session

    def tearDown(self) -> None:
        report_jobs_worker_module.get_session = self._old_get_session
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    async def test_process_pending_jobs_updates_heartbeat_without_jobs(self) -> None:
        worker = report_jobs_worker_module.ReportJobWorker()

        await worker._process_pending_jobs(bot=AsyncMock())

        with self.SessionLocal() as session:
            heartbeat = session.get(ServiceHeartbeat, "report_jobs_worker")
            self.assertIsNotNone(heartbeat)
            self.assertIsNotNone(heartbeat.updated_at)
            self.assertIsNotNone(heartbeat.host)
            self.assertIsNotNone(heartbeat.pid)

    async def test_heartbeat_is_updated_on_next_cycle_after_error(self) -> None:
        worker = report_jobs_worker_module.ReportJobWorker()

        with self.SessionLocal() as session:
            session.add(User(id=1, telegram_user_id=12345, telegram_username="worker"))
            session.add(
                ReportJob(
                    id=1,
                    user_id=1,
                    order_id=None,
                    tariff=Tariff.T1,
                    status=ReportJobStatus.PENDING,
                    attempts=0,
                    chat_id=12345,
                )
            )
            session.commit()

        with patch.object(worker, "_claim_job", return_value=True), patch.object(
            worker,
            "_handle_job",
            new=AsyncMock(side_effect=[RuntimeError("boom"), None]),
        ):
            with self.assertRaises(RuntimeError):
                await worker._process_pending_jobs(bot=AsyncMock())

            with self.SessionLocal() as session:
                first_heartbeat = session.get(ServiceHeartbeat, "report_jobs_worker")
                self.assertIsNotNone(first_heartbeat)
                first_updated_at = first_heartbeat.updated_at

            await worker._process_pending_jobs(bot=AsyncMock())

            with self.SessionLocal() as session:
                second_heartbeat = session.get(ServiceHeartbeat, "report_jobs_worker")
                self.assertIsNotNone(second_heartbeat)
                self.assertIsNotNone(first_updated_at)
                self.assertGreaterEqual(second_heartbeat.updated_at, first_updated_at)


if __name__ == "__main__":
    unittest.main()
