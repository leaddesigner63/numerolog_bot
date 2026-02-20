import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot import report_jobs_worker as worker_module
from app.db.base import Base
from app.db.models import ScreenStateRecord, User, UserProfile


class ReportJobsWorkerNudgeTests(unittest.IsolatedAsyncioTestCase):
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

        self._old_get_session = worker_module.get_session
        worker_module.get_session = _test_get_session

    def tearDown(self) -> None:
        worker_module.get_session = self._old_get_session
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    async def test_send_resume_nudge_once_for_stalled_user(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=1, telegram_user_id=19001, telegram_username="nudge")
            session.add(user)
            session.add(
                UserProfile(
                    user_id=1,
                    name="name",
                    birth_date="01.01.1990",
                    birth_place_city="Moscow",
                    birth_place_country="RU",
                    marketing_consent_document_version="v1",
                    marketing_consent_accepted_at=datetime.now(timezone.utc),
                )
            )
            session.add(
                ScreenStateRecord(
                    telegram_user_id=19001,
                    screen_id="S3",
                    message_ids=[],
                    user_message_ids=[],
                    last_question_message_id=None,
                    data={
                        "last_critical_step_at": (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat(),
                        "last_critical_screen_id": "S3",
                        "order_id": "321",
                    },
                )
            )
            session.commit()

        worker = worker_module.ReportJobWorker()
        with patch.object(worker_module, "send_marketing_message", new=AsyncMock(return_value=type("R", (), {"sent": True, "reason": "sent"})())), patch.object(
            worker_module.screen_manager,
            "_record_transition_event",
            return_value=None,
        ):
            await worker._process_stalled_users(bot=AsyncMock())
            await worker._process_stalled_users(bot=AsyncMock())

        with self.SessionLocal() as session:
            row = session.get(ScreenStateRecord, 19001)
            data = dict(row.data or {})
            self.assertIsNotNone(data.get("resume_nudge_sent_at"))
            self.assertEqual(data.get("resume_nudge_campaign"), "resume_after_stall_v1")


if __name__ == "__main__":
    unittest.main()
