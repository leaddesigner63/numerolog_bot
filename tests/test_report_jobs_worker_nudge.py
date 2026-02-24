import io
import logging
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot import report_jobs_worker as worker_module
from app.core.logging import ExtraFieldsFormatter
from app.db.base import Base
from app.db.models import (
    Order,
    OrderStatus,
    PaymentProvider,
    ScreenStateRecord,
    Tariff,
    User,
    UserProfile,
)


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

    def test_build_resume_deeplink_strips_at_sign_from_bot_username(self) -> None:
        worker = worker_module.ReportJobWorker()
        with patch.object(worker_module.settings, "telegram_bot_username", "@AlreadyUbot"):
            link = worker._build_resume_deeplink(state_data={"order_id": "321"})

        self.assertEqual(link, "https://t.me/AlreadyUbot?start=resume_nudge_321")

    def test_build_resume_deeplink_handles_whitespace_username(self) -> None:
        worker = worker_module.ReportJobWorker()
        with patch.object(worker_module.settings, "telegram_bot_username", "  @AlreadyUbot  "):
            link = worker._build_resume_deeplink(state_data={})

        self.assertEqual(link, "https://t.me/AlreadyUbot?start=resume_nudge")

    async def test_send_checkout_value_nudge_once_for_s2_after_due_at(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=2, telegram_user_id=19002, telegram_username="checkout")
            session.add(user)
            session.add(
                UserProfile(
                    user_id=2,
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
                    telegram_user_id=19002,
                    screen_id="S2",
                    message_ids=[],
                    user_message_ids=[],
                    last_question_message_id=None,
                    data={"order_id": "777"},
                )
            )
            session.commit()

        send_mock = AsyncMock(return_value=type("R", (), {"sent": True, "reason": "sent"})())
        worker = worker_module.ReportJobWorker()
        with patch.object(worker_module, "send_marketing_message", new=send_mock), patch.object(
            worker_module.screen_manager,
            "_record_transition_event",
            return_value=None,
        ), patch.object(worker_module.random, "randint", return_value=12):
            await worker._process_checkout_value_nudges(bot=AsyncMock())

        with self.SessionLocal() as session:
            row = session.get(ScreenStateRecord, 19002)
            data = dict(row.data or {})
            data["checkout_value_nudge_due_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            row.data = data
            session.add(row)
            session.commit()

        with patch.object(worker_module, "send_marketing_message", new=send_mock), patch.object(
            worker_module.screen_manager,
            "_record_transition_event",
            return_value=None,
        ):
            await worker._process_checkout_value_nudges(bot=AsyncMock())
            await worker._process_checkout_value_nudges(bot=AsyncMock())

        self.assertEqual(send_mock.await_count, 1)

        with self.SessionLocal() as session:
            row = session.get(ScreenStateRecord, 19002)
            data = dict(row.data or {})
            self.assertEqual(data.get("checkout_value_nudge_campaign"), "checkout_value_nudge_v1")
            self.assertEqual(data.get("checkout_value_nudge_delay_minutes"), 12)
            self.assertEqual(data.get("checkout_value_nudge_target_screen_id"), "S2")
            self.assertIsNotNone(data.get("checkout_value_nudge_sent_at"))

    async def test_checkout_value_nudge_skips_paid_users(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=3, telegram_user_id=19003, telegram_username="paid")
            session.add(user)
            session.add(
                UserProfile(
                    user_id=3,
                    name="name",
                    birth_date="01.01.1990",
                    birth_place_city="Moscow",
                    birth_place_country="RU",
                    marketing_consent_document_version="v1",
                    marketing_consent_accepted_at=datetime.now(timezone.utc),
                )
            )
            session.add(
                Order(
                    user_id=3,
                    tariff=Tariff.T1,
                    amount=560,
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PAID,
                )
            )
            session.add(
                ScreenStateRecord(
                    telegram_user_id=19003,
                    screen_id="S4",
                    message_ids=[],
                    user_message_ids=[],
                    last_question_message_id=None,
                    data={
                        "checkout_value_nudge_due_at": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
                        "checkout_value_nudge_target_screen_id": "S4",
                    },
                )
            )
            session.commit()

        send_mock = AsyncMock(return_value=type("R", (), {"sent": True, "reason": "sent"})())
        worker = worker_module.ReportJobWorker()
        with patch.object(worker_module, "send_marketing_message", new=send_mock):
            await worker._process_checkout_value_nudges(bot=AsyncMock())

        self.assertEqual(send_mock.await_count, 0)

    async def test_resume_nudge_logs_traceback_and_context_on_failure(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=4, telegram_user_id=19011, telegram_username="resume_fail")
            session.add(user)
            session.add(
                UserProfile(
                    user_id=4,
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
                    telegram_user_id=19011,
                    screen_id="S3",
                    message_ids=[],
                    user_message_ids=[],
                    last_question_message_id=None,
                    data={
                        "last_critical_step_at": (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat(),
                        "last_critical_screen_id": "S3",
                    },
                )
            )
            session.commit()

        logger = logging.getLogger(worker_module.__name__)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(ExtraFieldsFormatter("%(levelname)s|%(name)s|%(message)s%(extra_fields)s"))
        old_handlers = logger.handlers[:]
        old_level = logger.level
        old_propagate = logger.propagate
        logger.handlers = [handler]
        logger.setLevel(logging.WARNING)
        logger.propagate = False

        worker = worker_module.ReportJobWorker()
        try:
            with patch.object(worker_module, "send_marketing_message", new=AsyncMock(side_effect=RuntimeError("resume boom"))):
                await worker._process_stalled_users(bot=AsyncMock())
        finally:
            logger.handlers = old_handlers
            logger.level = old_level
            logger.propagate = old_propagate

        output = stream.getvalue()
        self.assertIn("resume_nudge_process_failed", output)
        self.assertIn("telegram_user_id=19011", output)
        self.assertIn("error=resume boom", output)
        self.assertIn("Traceback", output)
        self.assertIn("RuntimeError: resume boom", output)

    async def test_checkout_value_nudge_logs_traceback_and_context_on_failure(self) -> None:
        with self.SessionLocal() as session:
            user = User(id=5, telegram_user_id=19012, telegram_username="checkout_fail")
            session.add(user)
            session.add(
                UserProfile(
                    user_id=5,
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
                    telegram_user_id=19012,
                    screen_id="S7",
                    message_ids=[],
                    user_message_ids=[],
                    last_question_message_id=None,
                    data={
                        "checkout_value_nudge_due_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                    },
                )
            )
            session.commit()

        logger = logging.getLogger(worker_module.__name__)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(ExtraFieldsFormatter("%(levelname)s|%(name)s|%(message)s%(extra_fields)s"))
        old_handlers = logger.handlers[:]
        old_level = logger.level
        old_propagate = logger.propagate
        logger.handlers = [handler]
        logger.setLevel(logging.WARNING)
        logger.propagate = False

        worker = worker_module.ReportJobWorker()
        try:
            with patch.object(worker_module, "send_marketing_message", new=AsyncMock(side_effect=RuntimeError("checkout boom"))):
                await worker._process_checkout_value_nudges(bot=AsyncMock())
        finally:
            logger.handlers = old_handlers
            logger.level = old_level
            logger.propagate = old_propagate

        output = stream.getvalue()
        self.assertIn("checkout_value_nudge_process_failed", output)
        self.assertIn("telegram_user_id=19012", output)
        self.assertIn("error=checkout boom", output)
        self.assertIn("Traceback", output)
        self.assertIn("RuntimeError: checkout boom", output)

    async def test_nudges_skip_invalid_state_data_type_without_failures(self) -> None:
        with self.SessionLocal() as session:
            session.add(
                ScreenStateRecord(
                    telegram_user_id=19020,
                    screen_id="S2",
                    message_ids=[],
                    user_message_ids=[],
                    last_question_message_id=None,
                    data=["broken", "payload"],
                )
            )
            session.add(
                ScreenStateRecord(
                    telegram_user_id=19021,
                    screen_id="S3",
                    message_ids=[],
                    user_message_ids=[],
                    last_question_message_id=None,
                    data="broken-payload",
                )
            )
            session.commit()

        logger = logging.getLogger(worker_module.__name__)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(ExtraFieldsFormatter("%(levelname)s|%(name)s|%(message)s%(extra_fields)s"))
        old_handlers = logger.handlers[:]
        old_level = logger.level
        old_propagate = logger.propagate
        logger.handlers = [handler]
        logger.setLevel(logging.WARNING)
        logger.propagate = False

        send_mock = AsyncMock(return_value=type("R", (), {"sent": True, "reason": "sent"})())
        worker = worker_module.ReportJobWorker()
        try:
            with patch.object(worker_module, "send_marketing_message", new=send_mock), patch.object(
                worker_module.screen_manager,
                "_record_transition_event",
                return_value=None,
            ) as event_mock:
                await worker._process_stalled_users(bot=AsyncMock())
                await worker._process_checkout_value_nudges(bot=AsyncMock())
        finally:
            logger.handlers = old_handlers
            logger.level = old_level
            logger.propagate = old_propagate

        output = stream.getvalue()
        self.assertIn("nudge_state_skipped", output)
        self.assertIn("reason=invalid_state_data_type", output)
        self.assertIn("state_data_type=list", output)
        self.assertIn("state_data_type=str", output)
        self.assertNotIn("resume_nudge_process_failed", output)
        self.assertNotIn("checkout_value_nudge_process_failed", output)
        self.assertNotIn("Traceback", output)
        self.assertEqual(send_mock.await_count, 0)
        self.assertGreaterEqual(event_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
