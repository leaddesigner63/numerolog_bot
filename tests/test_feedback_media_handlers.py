import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.handlers.feedback import handle_feedback_document, handle_feedback_photo


class FeedbackMediaHandlersTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_feedback_photo_submits_attachment_and_deletes_message(self) -> None:
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=1001, username="tester"),
            bot=SimpleNamespace(),
            chat=SimpleNamespace(id=2002),
            message_id=3003,
            caption="чек",
            photo=[SimpleNamespace(file_id="photo-small"), SimpleNamespace(file_id="photo-big")],
        )

        with (
            patch("app.bot.handlers.feedback._submit_feedback", new=AsyncMock()) as submit_feedback,
            patch("app.bot.handlers.feedback.screen_manager.add_user_message_id") as add_message_id,
            patch("app.bot.handlers.feedback.screen_manager.delete_user_message", new=AsyncMock()) as delete_user_message,
        ):
            await handle_feedback_photo(message)

        add_message_id.assert_called_once_with(1001, 3003)
        submit_feedback.assert_awaited_once_with(
            message.bot,
            user_id=1001,
            username="tester",
            feedback_text="чек",
            attachment_type="photo",
            attachment_file_id="photo-big",
            attachment_caption="чек",
        )
        delete_user_message.assert_awaited_once_with(
            bot=message.bot,
            chat_id=2002,
            user_id=1001,
            message_id=3003,
        )

    async def test_handle_feedback_document_submits_attachment_and_deletes_message(self) -> None:
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=1001, username="tester"),
            bot=SimpleNamespace(),
            chat=SimpleNamespace(id=2002),
            message_id=3003,
            caption="документ",
            document=SimpleNamespace(file_id="doc-file"),
        )

        with (
            patch("app.bot.handlers.feedback._submit_feedback", new=AsyncMock()) as submit_feedback,
            patch("app.bot.handlers.feedback.screen_manager.add_user_message_id") as add_message_id,
            patch("app.bot.handlers.feedback.screen_manager.delete_user_message", new=AsyncMock()) as delete_user_message,
        ):
            await handle_feedback_document(message)

        add_message_id.assert_called_once_with(1001, 3003)
        submit_feedback.assert_awaited_once_with(
            message.bot,
            user_id=1001,
            username="tester",
            feedback_text="документ",
            attachment_type="document",
            attachment_file_id="doc-file",
            attachment_caption="документ",
        )
        delete_user_message.assert_awaited_once_with(
            bot=message.bot,
            chat_id=2002,
            user_id=1001,
            message_id=3003,
        )


if __name__ == "__main__":
    unittest.main()
