import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.handlers import profile


class ProfileInputKeyboardCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_profile_wizard_clears_screen_inline_keyboard(self) -> None:
        state = AsyncMock()
        message = SimpleNamespace(
            bot=AsyncMock(),
            chat=SimpleNamespace(id=100),
        )
        message.bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=55))

        with patch.object(
            profile.screen_manager,
            "enter_text_input_mode",
            new=AsyncMock(),
        ) as enter_mode, patch.object(profile.screen_manager, "update_last_question_message_id"):
            await profile.start_profile_wizard(message, state, user_id=7)

        enter_mode.assert_awaited_once_with(bot=message.bot, chat_id=100, user_id=7)

    async def test_start_profile_edit_text_clears_screen_inline_keyboard(self) -> None:
        state = AsyncMock()
        callback = SimpleNamespace(
            bot=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id=100)),
            from_user=SimpleNamespace(id=7),
        )
        callback.bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=77))

        with patch.object(profile.screen_manager, "delete_last_question_message", new=AsyncMock()), patch.object(
            profile.screen_manager,
            "enter_text_input_mode",
            new=AsyncMock(),
        ) as enter_mode, patch.object(profile.screen_manager, "update_last_question_message_id"):
            await profile._start_profile_edit(
                callback,
                state,
                profile.ProfileStates.edit_name,
                "Введите новое имя",
                reply_markup=None,
            )

        enter_mode.assert_awaited_once_with(
            bot=callback.bot,
            chat_id=100,
            user_id=7,
            preserve_last_question=True,
        )


if __name__ == "__main__":
    unittest.main()
