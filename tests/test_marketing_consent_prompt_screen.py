import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.handlers import screens
from app.bot.screens import SCREEN_REGISTRY


class MarketingConsentPromptScreenTests(unittest.IsolatedAsyncioTestCase):
    def test_marketing_consent_screen_registered_with_required_buttons(self) -> None:
        content = SCREEN_REGISTRY["S_MARKETING_CONSENT"]({})

        self.assertIn("подпис", content.messages[0].lower())
        self.assertIn("newsletter-consent", content.messages[0])
        self.assertIsNotNone(content.keyboard)
        callback_data = [
            button.callback_data
            for row in content.keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertIn("marketing:consent:accept", callback_data)
        self.assertIn("marketing:consent:skip", callback_data)

    async def test_show_post_report_screen_uses_marketing_screen_when_due(self) -> None:
        state_data: dict[str, str] = {}

        def _update_state(_user_id: int, **kwargs):
            if kwargs:
                state_data.update(kwargs)
            return SimpleNamespace(data=state_data.copy())

        with (
            patch.object(screens.screen_manager, "update_state", side_effect=_update_state),
            patch.object(
                screens.screen_manager,
                "show_screen",
                new=AsyncMock(return_value=True),
            ) as show_screen,
        ):
            delivered = await screens.show_post_report_screen(
                bot=AsyncMock(),
                chat_id=100,
                user_id=200,
            )

        self.assertTrue(delivered)
        show_screen.assert_awaited_once()
        self.assertEqual(show_screen.await_args.kwargs["screen_id"], "S_MARKETING_CONSENT")
        self.assertEqual(state_data.get("marketing_consent_return_screen"), "S7")


if __name__ == "__main__":
    unittest.main()
