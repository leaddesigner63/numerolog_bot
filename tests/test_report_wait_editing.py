import unittest
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest

from app.bot.handlers.screens import _edit_report_wait_message


class ReportWaitEditingTests(unittest.IsolatedAsyncioTestCase):
    async def test_falls_back_to_caption_for_photo_messages(self) -> None:
        bot = AsyncMock()
        bot.edit_message_text.side_effect = TelegramBadRequest(
            method="editMessageText",
            message="Bad Request: there is no text in the message to edit",
        )

        await _edit_report_wait_message(
            bot=bot,
            chat_id=1,
            message_id=2,
            text="Тест",
            reply_markup=None,
            parse_mode=None,
        )

        bot.edit_message_text.assert_awaited_once()
        bot.edit_message_caption.assert_awaited_once_with(
            chat_id=1,
            message_id=2,
            caption="Тест",
            reply_markup=None,
            parse_mode=None,
        )

    async def test_reraises_unexpected_edit_error(self) -> None:
        bot = AsyncMock()
        bot.edit_message_text.side_effect = TelegramBadRequest(
            method="editMessageText",
            message="Bad Request: message to edit not found",
        )

        with self.assertRaises(TelegramBadRequest):
            await _edit_report_wait_message(
                bot=bot,
                chat_id=1,
                message_id=2,
                text="Тест",
                reply_markup=None,
                parse_mode=None,
            )

        bot.edit_message_caption.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
