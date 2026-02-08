import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.admin import _load_feedback_thread_history
from app.bot.handlers.screens import _build_feedback_records, _extract_quick_reply_thread_id
from app.db.base import Base
from app.db.models import (
    FeedbackMessage,
    FeedbackStatus,
    SupportDialogMessage,
    SupportMessageDirection,
    User,
)


class SupportThreadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_extract_quick_reply_thread_id(self) -> None:
        self.assertEqual(_extract_quick_reply_thread_id("feedback:quick_reply:42"), 42)
        self.assertIsNone(_extract_quick_reply_thread_id("feedback:quick_reply:bad"))
        self.assertIsNone(_extract_quick_reply_thread_id("feedback:send"))
        self.assertIsNone(_extract_quick_reply_thread_id(None))

    def test_reply_flow_keeps_same_thread(self) -> None:
        sent_at = datetime.now(timezone.utc)
        with self.Session() as session:
            user = User(telegram_user_id=777001)
            session.add(user)
            session.flush()

            root_feedback = FeedbackMessage(
                user_id=user.id,
                text="Первое сообщение",
                status=FeedbackStatus.SENT,
                sent_at=sent_at,
            )
            session.add(root_feedback)
            session.flush()

            admin_message = SupportDialogMessage(
                user_id=user.id,
                thread_feedback_id=root_feedback.id,
                direction=SupportMessageDirection.ADMIN,
                text="Ответ поддержки",
                delivered=True,
            )
            session.add(admin_message)

            feedback, support_message, _ = _build_feedback_records(
                user_id=user.id,
                feedback_text="Быстрый ответ пользователя",
                status=FeedbackStatus.SENT,
                sent_at=sent_at,
                thread_feedback_id=root_feedback.id,
            )
            session.add(feedback)
            session.flush()
            support_message.thread_feedback_id = root_feedback.id
            session.add(support_message)
            session.commit()

            stored_feedback = session.query(FeedbackMessage).filter(FeedbackMessage.id == feedback.id).one()
            self.assertEqual(stored_feedback.parent_feedback_id, root_feedback.id)

            stored_support_message = (
                session.query(SupportDialogMessage)
                .filter(SupportDialogMessage.text == "Быстрый ответ пользователя")
                .one()
            )
            self.assertEqual(stored_support_message.thread_feedback_id, root_feedback.id)
            self.assertEqual(stored_support_message.direction, SupportMessageDirection.USER)

    def test_admin_fallback_thread_history_marks_delivered(self) -> None:
        sent_at = datetime.now(timezone.utc)
        with self.Session() as session:
            user = User(telegram_user_id=777002)
            session.add(user)
            session.flush()

            root_feedback = FeedbackMessage(
                user_id=user.id,
                text="Сообщение пользователя",
                status=FeedbackStatus.SENT,
                sent_at=sent_at,
            )
            session.add(root_feedback)
            session.commit()

            history = _load_feedback_thread_history(
                session,
                thread_feedback_id=root_feedback.id,
                limit=50,
            )

            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["direction"], "user")
            self.assertTrue(history[0]["delivered"])


if __name__ == "__main__":
    unittest.main()
