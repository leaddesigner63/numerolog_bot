import unittest
from unittest.mock import AsyncMock, patch

from app.bot.handlers.screen_manager import ScreenManager


class TextInputModeHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_enter_text_input_mode_deletes_last_question_by_default(self) -> None:
        manager = ScreenManager()
        bot = AsyncMock()

        with patch.object(manager, "delete_last_question_message", new=AsyncMock()) as delete_last, patch.object(
            manager,
            "clear_current_screen_inline_keyboards",
            new=AsyncMock(),
        ) as clear_inline:
            await manager.enter_text_input_mode(bot=bot, chat_id=101, user_id=7)

        delete_last.assert_awaited_once_with(bot=bot, chat_id=101, user_id=7)
        clear_inline.assert_awaited_once_with(bot=bot, chat_id=101, user_id=7)

    async def test_enter_text_input_mode_preserve_last_question(self) -> None:
        manager = ScreenManager()
        bot = AsyncMock()

        with patch.object(manager, "delete_last_question_message", new=AsyncMock()) as delete_last, patch.object(
            manager,
            "clear_current_screen_inline_keyboards",
            new=AsyncMock(),
        ) as clear_inline:
            await manager.enter_text_input_mode(
                bot=bot,
                chat_id=101,
                user_id=7,
                preserve_last_question=True,
            )

        delete_last.assert_not_awaited()
        clear_inline.assert_awaited_once_with(bot=bot, chat_id=101, user_id=7)


if __name__ == "__main__":
    unittest.main()
