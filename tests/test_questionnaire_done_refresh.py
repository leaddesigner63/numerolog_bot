import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.bot.handlers import screens


class QuestionnaireDoneRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_done_refreshes_questionnaire_state_before_checks(self) -> None:
        callback = SimpleNamespace(
            data="questionnaire:done",
            from_user=SimpleNamespace(id=7, username="tester"),
            message=SimpleNamespace(chat=SimpleNamespace(id=11)),
            bot=AsyncMock(),
            answer=AsyncMock(),
        )
        state = AsyncMock()

        state_snapshot = SimpleNamespace(
            data={
                "selected_tariff": None,
                "order_id": None,
                "questionnaire": {"status": "in_progress"},
                "personal_data_consent_accepted": True,
            }
        )

        fake_session = MagicMock()

        class _SessionContext:
            def __enter__(self_inner):
                return fake_session

            def __exit__(self_inner, exc_type, exc, tb):
                return False

        with (
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock(return_value=True)),
            patch.object(screens, "_send_notice", new=AsyncMock()),
            patch.object(screens, "_maybe_run_report_delay", new=AsyncMock()),
            patch.object(screens, "_create_report_job", return_value=SimpleNamespace(id=1)),
            patch.object(screens, "_get_or_create_user", return_value=SimpleNamespace(id=9)),
            patch.object(screens, "get_session", return_value=_SessionContext()),
            patch.object(screens, "_refresh_questionnaire_state") as refresh_questionnaire_state,
            patch.object(screens, "_refresh_profile_state") as refresh_profile_state,
            patch.object(screens.screen_manager, "update_state", return_value=state_snapshot),
        ):
            await screens.handle_callbacks(callback, state)

        refresh_questionnaire_state.assert_called_once_with(fake_session, 7)
        refresh_profile_state.assert_called_once_with(fake_session, 7)


if __name__ == "__main__":
    unittest.main()
