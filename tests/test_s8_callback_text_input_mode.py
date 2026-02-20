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

    async def test_show_screen_for_callback_manual_s4_forces_profile_scenario(self) -> None:
        callback = SimpleNamespace(
            bot=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id=123)),
            from_user=SimpleNamespace(id=77),
            data="screen:S4",
        )
        state_snapshot = SimpleNamespace(
            data={screens.S4_SCENARIO_STATE_KEY: screens.S4_SCENARIO_AFTER_PAYMENT}
        )

        with patch.object(
            screens.screen_manager,
            "get_state",
            return_value=SimpleNamespace(screen_id="S1"),
        ), patch.object(
            screens.screen_manager,
            "update_state",
            side_effect=[state_snapshot, state_snapshot],
        ) as update_state, patch.object(
            screens.screen_manager,
            "show_screen",
            new=AsyncMock(return_value=True),
        ):
            await screens._show_screen_for_callback(callback, screen_id="S4")

        self.assertEqual(update_state.call_count, 2)
        self.assertEqual(
            update_state.call_args_list[1].kwargs,
            {screens.S4_SCENARIO_STATE_KEY: screens.S4_SCENARIO_PROFILE},
        )

    async def test_show_screen_for_callback_non_manual_s4_keeps_after_payment_scenario(self) -> None:
        callback = SimpleNamespace(
            bot=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id=123)),
            from_user=SimpleNamespace(id=77),
            data="payment:check",
        )
        state_snapshot = SimpleNamespace(
            data={screens.S4_SCENARIO_STATE_KEY: screens.S4_SCENARIO_AFTER_PAYMENT}
        )

        with patch.object(
            screens.screen_manager,
            "get_state",
            return_value=SimpleNamespace(screen_id="S1"),
        ), patch.object(
            screens.screen_manager,
            "update_state",
            return_value=state_snapshot,
        ) as update_state, patch.object(
            screens.screen_manager,
            "show_screen",
            new=AsyncMock(return_value=True),
        ):
            await screens._show_screen_for_callback(callback, screen_id="S4")

        self.assertEqual(update_state.call_count, 1)


if __name__ == "__main__":
    unittest.main()
