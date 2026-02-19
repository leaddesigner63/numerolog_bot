import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.handlers import profile, questionnaire
from app.db.models import Tariff


class ProfileQuestionnaireAccessGuardsTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_access_for_paid_tariff_does_not_require_paid_order(self) -> None:
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=101),
            message=SimpleNamespace(chat=SimpleNamespace(id=202)),
            bot=AsyncMock(),
        )
        state_snapshot = SimpleNamespace(data={"selected_tariff": Tariff.T1.value})

        with (
            patch.object(profile.screen_manager, "update_state", return_value=state_snapshot),
            patch.object(profile.screen_manager, "send_ephemeral_message", new=AsyncMock()) as send_ephemeral,
            patch.object(profile.screen_manager, "show_screen", new=AsyncMock()) as show_screen,
        ):
            allowed = await profile._ensure_profile_access(callback)

        self.assertTrue(allowed)
        send_ephemeral.assert_not_awaited()
        show_screen.assert_not_awaited()

    async def test_questionnaire_access_for_t2_does_not_require_paid_order(self) -> None:
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=101),
            message=SimpleNamespace(chat=SimpleNamespace(id=202)),
            bot=AsyncMock(),
        )
        state_snapshot = SimpleNamespace(data={"selected_tariff": Tariff.T2.value})

        with (
            patch.object(questionnaire.screen_manager, "update_state", return_value=state_snapshot),
            patch.object(questionnaire.screen_manager, "send_ephemeral_message", new=AsyncMock()) as send_ephemeral,
            patch.object(questionnaire.screen_manager, "show_screen", new=AsyncMock()) as show_screen,
        ):
            allowed = await questionnaire._ensure_questionnaire_access(callback)

        self.assertTrue(allowed)
        send_ephemeral.assert_not_awaited()
        show_screen.assert_not_awaited()

    async def test_questionnaire_access_blocks_non_t2_t3_tariff(self) -> None:
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=101),
            message=SimpleNamespace(chat=SimpleNamespace(id=202)),
            bot=AsyncMock(),
        )
        state_snapshot = SimpleNamespace(data={"selected_tariff": Tariff.T1.value})

        with (
            patch.object(questionnaire.screen_manager, "update_state", return_value=state_snapshot),
            patch.object(questionnaire.screen_manager, "send_ephemeral_message", new=AsyncMock()) as send_ephemeral,
            patch.object(questionnaire.screen_manager, "show_screen", new=AsyncMock()) as show_screen,
        ):
            allowed = await questionnaire._ensure_questionnaire_access(callback)

        self.assertFalse(allowed)
        send_ephemeral.assert_awaited_once()
        show_screen.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
