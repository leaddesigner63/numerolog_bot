import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.handlers import screens


class S8CallbackTextInputModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_show_screen_for_callback_s8_calls_enter_text_input_mode(self) -> None:
        callback = SimpleNamespace(
            bot=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id=123)),
            from_user=SimpleNamespace(id=77),
            data="screen:S8",
        )

        with patch.object(screens.screen_manager, "enter_text_input_mode", new=AsyncMock()) as enter_mode, patch.object(
            screens.screen_manager,
            "show_screen",
            new=AsyncMock(return_value=True),
        ) as show_screen:
            result = await screens._show_screen_for_callback(callback, screen_id="S8")

        self.assertTrue(result)
        enter_mode.assert_awaited_once_with(bot=callback.bot, chat_id=123, user_id=77)
        show_screen.assert_awaited_once()

    async def test_show_screen_for_callback_non_s8_skips_enter_text_input_mode(self) -> None:
        callback = SimpleNamespace(
            bot=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id=123)),
            from_user=SimpleNamespace(id=77),
            data="screen:S1",
        )

        with patch.object(screens.screen_manager, "enter_text_input_mode", new=AsyncMock()) as enter_mode, patch.object(
            screens.screen_manager,
            "show_screen",
            new=AsyncMock(return_value=True),
        ):
            await screens._show_screen_for_callback(callback, screen_id="S1")

        enter_mode.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
