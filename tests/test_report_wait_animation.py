import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.bot.handlers import screens


class ReportWaitAnimationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fallbacks_to_caption_update_when_message_is_photo(self) -> None:
        bot = SimpleNamespace(
            edit_message_text=AsyncMock(side_effect=RuntimeError("not text message")),
            edit_message_caption=AsyncMock(return_value=True),
        )

        updated = await screens._update_report_wait_message(
            bot,
            chat_id=1,
            message_id=2,
            text="progress",
            reply_markup=None,
            parse_mode="HTML",
            user_id=42,
        )

        self.assertTrue(updated)
        bot.edit_message_text.assert_awaited_once()
        bot.edit_message_caption.assert_awaited_once()

    async def test_reports_failure_when_both_update_modes_failed(self) -> None:
        bot = SimpleNamespace(
            edit_message_text=AsyncMock(side_effect=RuntimeError("text fail")),
            edit_message_caption=AsyncMock(side_effect=RuntimeError("caption fail")),
        )

        updated = await screens._update_report_wait_message(
            bot,
            chat_id=1,
            message_id=2,
            text="progress",
            reply_markup=None,
            parse_mode="HTML",
            user_id=42,
        )

        self.assertFalse(updated)
        bot.edit_message_text.assert_awaited_once()
        bot.edit_message_caption.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
