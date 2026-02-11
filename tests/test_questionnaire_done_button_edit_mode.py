import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.bot.handlers import questionnaire


class QuestionnaireDoneButtonEditModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_edit_mode_uses_done_button_to_return_s5(self) -> None:
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=101, username="tester"),
            chat=SimpleNamespace(id=202),
            bot=AsyncMock(),
        )
        state = AsyncMock()
        state.get_data = AsyncMock(
            return_value={
                "questionnaire_mode": "edit",
                "current_question_id": "q1",
                "answers": {},
            }
        )

        question = SimpleNamespace(question_id="q1", question_type="text", options=[], scale=None)
        config = SimpleNamespace(
            version="v1",
            questions={"q1": question},
            get_question=lambda question_id: question if question_id == "q1" else None,
        )

        fake_response = SimpleNamespace()

        fake_session = MagicMock()

        class _SessionContext:
            def __enter__(self_inner):
                return fake_session

            def __exit__(self_inner, exc_type, exc, tb):
                return False

        with (
            patch.object(questionnaire, "load_questionnaire_config", return_value=config),
            patch.object(questionnaire, "_build_actual_answers", return_value=({}, "q1")),
            patch.object(questionnaire, "resolve_next_question_id", return_value=None),
            patch.object(questionnaire, "get_session", return_value=_SessionContext()),
            patch.object(questionnaire, "_get_or_create_user", return_value=SimpleNamespace(id=1)),
            patch.object(questionnaire, "_upsert_progress", return_value=fake_response),
            patch.object(questionnaire, "_question_payload", return_value={"questionnaire": {}}),
            patch.object(questionnaire, "_update_screen_state"),
            patch.object(questionnaire.screen_manager, "send_ephemeral_message", new=AsyncMock()) as send_ephemeral_message,
        ):
            await questionnaire._handle_answer(
                message=message,
                state=state,
                answer="Ответ",
                question_id="q1",
            )

        state.clear.assert_awaited_once()
        send_ephemeral_message.assert_awaited_once()
        keyboard = send_ephemeral_message.await_args.kwargs["reply_markup"]
        self.assertEqual(
            keyboard.inline_keyboard[0][0].callback_data,
            "screen:S5",
        )



    async def test_completed_edit_mode_uses_done_button_to_return_custom_screen(self) -> None:
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=101, username="tester"),
            chat=SimpleNamespace(id=202),
            bot=AsyncMock(),
        )
        state = AsyncMock()
        state.get_data = AsyncMock(
            return_value={
                "questionnaire_mode": "edit",
                "questionnaire_return_screen": "S11",
                "current_question_id": "q1",
                "answers": {},
            }
        )

        question = SimpleNamespace(question_id="q1", question_type="text", options=[], scale=None)
        config = SimpleNamespace(
            version="v1",
            questions={"q1": question},
            get_question=lambda question_id: question if question_id == "q1" else None,
        )

        fake_response = SimpleNamespace()

        fake_session = MagicMock()

        class _SessionContext:
            def __enter__(self_inner):
                return fake_session

            def __exit__(self_inner, exc_type, exc, tb):
                return False

        with (
            patch.object(questionnaire, "load_questionnaire_config", return_value=config),
            patch.object(questionnaire, "_build_actual_answers", return_value=({}, "q1")),
            patch.object(questionnaire, "resolve_next_question_id", return_value=None),
            patch.object(questionnaire, "get_session", return_value=_SessionContext()),
            patch.object(questionnaire, "_get_or_create_user", return_value=SimpleNamespace(id=1)),
            patch.object(questionnaire, "_upsert_progress", return_value=fake_response),
            patch.object(questionnaire, "_question_payload", return_value={"questionnaire": {}}),
            patch.object(questionnaire, "_update_screen_state"),
            patch.object(questionnaire.screen_manager, "send_ephemeral_message", new=AsyncMock()) as send_ephemeral_message,
        ):
            await questionnaire._handle_answer(
                message=message,
                state=state,
                answer="Ответ",
                question_id="q1",
            )

        state.clear.assert_awaited_once()
        send_ephemeral_message.assert_awaited_once()
        keyboard = send_ephemeral_message.await_args.kwargs["reply_markup"]
        self.assertEqual(
            keyboard.inline_keyboard[0][0].callback_data,
            "screen:S11",
        )


    def test_delete_questionnaire_confirm_keyboard_has_confirm_and_cancel(self) -> None:
        keyboard = questionnaire._build_delete_questionnaire_confirm_keyboard()
        callbacks = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertIn("questionnaire:delete:lk:confirm", callbacks)
        self.assertIn("questionnaire:delete:lk:cancel", callbacks)

    async def test_delete_from_lk_shows_confirmation_instead_of_immediate_delete(self) -> None:
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=101, username="tester"),
            message=SimpleNamespace(chat=SimpleNamespace(id=202)),
            bot=AsyncMock(),
            answer=AsyncMock(),
        )
        state = AsyncMock()

        with (
            patch.object(questionnaire, "_ensure_paid_access", new=AsyncMock(return_value=True)),
            patch.object(questionnaire, "_ensure_profile_ready", new=AsyncMock(return_value=True)),
            patch.object(questionnaire.screen_manager, "send_ephemeral_message", new=AsyncMock()) as send_ephemeral_message,
            patch.object(questionnaire, "load_questionnaire_config") as load_questionnaire_config,
        ):
            await questionnaire.delete_questionnaire_from_lk(callback, state)

        send_ephemeral_message.assert_awaited_once()
        args = send_ephemeral_message.await_args.args
        kwargs = send_ephemeral_message.await_args.kwargs
        self.assertIn("Вы уверены", args[1])
        keyboard = kwargs["reply_markup"]
        callbacks = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertIn("questionnaire:delete:lk:confirm", callbacks)
        self.assertIn("questionnaire:delete:lk:cancel", callbacks)
        load_questionnaire_config.assert_not_called()

if __name__ == "__main__":
    unittest.main()
