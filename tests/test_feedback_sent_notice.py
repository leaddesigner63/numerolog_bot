import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.handlers.feedback import handle_feedback_text
from app.bot.handlers.screens import FEEDBACK_SENT_NOTICE
from app.db.models import FeedbackStatus


class FeedbackSentNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_feedback_text_uses_admin_reply_notice(self) -> None:
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=1001, username="tester"),
            bot=SimpleNamespace(),
            chat=SimpleNamespace(id=2002),
            message_id=3003,
            text="проверка",
        )

        with (
            patch("app.bot.handlers.feedback._submit_feedback", new=AsyncMock(return_value=FeedbackStatus.SENT)),
            patch("app.bot.handlers.feedback.screen_manager.add_user_message_id") as add_message_id,
            patch("app.bot.handlers.feedback.screen_manager.update_state") as update_state,
            patch("app.bot.handlers.feedback.screen_manager.send_ephemeral_message", new=AsyncMock()) as send_notice,
            patch("app.bot.handlers.feedback.screen_manager.delete_user_message", new=AsyncMock()) as delete_user_message,
        ):
            await handle_feedback_text(message)

        add_message_id.assert_called_once_with(1001, 3003)
        send_notice.assert_awaited_once_with(
            message,
            FEEDBACK_SENT_NOTICE,
            delete_delay_seconds=5,
        )
        delete_user_message.assert_awaited_once_with(
            bot=message.bot,
            chat_id=2002,
            user_id=1001,
            message_id=3003,
        )
        self.assertEqual(update_state.call_count, 2)


if __name__ == "__main__":
    unittest.main()
