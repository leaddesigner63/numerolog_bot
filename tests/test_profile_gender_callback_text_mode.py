import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.handlers import profile


class ProfileGenderCallbackTextModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_gender_callback_switch_to_birth_date_uses_text_input_mode(self) -> None:
        callback = SimpleNamespace(
            data="profile:gender:female",
            bot=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id=200)),
            from_user=SimpleNamespace(id=10),
            answer=AsyncMock(),
        )
        callback.bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=300))

        state = AsyncMock()
        state.get_state = AsyncMock(return_value=profile.ProfileStates.gender.state)

        with patch.object(profile.screen_manager, "delete_last_question_message", new=AsyncMock()), patch.object(
            profile.screen_manager,
            "enter_text_input_mode",
            new=AsyncMock(),
        ) as enter_mode, patch.object(profile.screen_manager, "update_last_question_message_id"):
            await profile.handle_profile_gender_callback(callback, state)

        enter_mode.assert_awaited_once_with(
            bot=callback.bot,
            chat_id=200,
            user_id=10,
            preserve_last_question=True,
        )


if __name__ == "__main__":
    unittest.main()
