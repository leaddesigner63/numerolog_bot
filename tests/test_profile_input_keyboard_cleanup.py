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

        enter_mode.assert_awaited_once_with(
            bot=message.bot,
            chat_id=100,
            user_id=7,
            cleanup_mode="delete_messages",
        )

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
            cleanup_mode="delete_messages",
        )

    async def test_accept_consent_uses_cleanup_friendly_screen_manager_messages(self) -> None:
        callback = SimpleNamespace(
            bot=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id=100), answer=AsyncMock()),
            from_user=SimpleNamespace(id=7, username="tester"),
            answer=AsyncMock(),
        )

        with (
            patch.object(profile, "get_session") as get_session,
            patch.object(profile, "_get_or_create_user") as get_or_create_user,
            patch.object(profile.screen_manager, "update_state") as update_state,
            patch.object(profile.screen_manager, "send_ephemeral_message", new=AsyncMock()) as send_ephemeral,
            patch.object(profile.screen_manager, "show_screen", new=AsyncMock()) as show_screen,
        ):
            fake_session = get_session.return_value.__enter__.return_value
            fake_profile = SimpleNamespace(
                name="Иван",
                gender="Мужской",
                birth_date="2000-01-01",
                birth_time="10:00",
                birth_place_city="Москва",
                birth_place_region="Московская область",
                birth_place_country="Россия",
                personal_data_consent_accepted_at=None,
                personal_data_consent_source=None,
            )
            fake_session.flush = lambda: None
            get_or_create_user.return_value = SimpleNamespace(profile=fake_profile)
            update_state.side_effect = [
                None,
                SimpleNamespace(data={"selected_tariff": "T2"}),
                None,
            ]

            await profile.accept_profile_consent(callback)

        send_ephemeral.assert_awaited_once()
        show_screen.assert_awaited_once()
        callback.message.answer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
