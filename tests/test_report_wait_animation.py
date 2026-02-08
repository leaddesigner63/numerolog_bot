import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.bot.handlers import screens

from unittest.mock import patch


class _State:
    def __init__(self, message_ids, data=None):
        self.message_ids = message_ids
        self.data = data or {}



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

    async def test_run_report_delay_uses_latest_message_id_from_state(self) -> None:
        bot = SimpleNamespace()
        states = [
            _State([100], {}),
            _State([100], {}),
            _State([101], {}),
        ]

        with patch.object(screens.settings, "report_delay_seconds", 2), patch.object(
            screens.screen_manager,
            "update_state",
            side_effect=states,
        ), patch.object(
            screens.screen_manager,
            "render_screen",
            return_value=SimpleNamespace(keyboard=None, parse_mode="HTML"),
        ), patch.object(
            screens,
            "_update_report_wait_message",
            new=AsyncMock(return_value=True),
        ) as update_mock, patch.object(screens.asyncio, "sleep", new=AsyncMock()):
            await screens._run_report_delay(bot=bot, chat_id=1, user_id=42)

        self.assertEqual(update_mock.await_count, 2)
        first_call = update_mock.await_args_list[0].kwargs
        second_call = update_mock.await_args_list[1].kwargs
        self.assertEqual(first_call["message_id"], 100)
        self.assertEqual(second_call["message_id"], 101)


if __name__ == "__main__":
    unittest.main()
