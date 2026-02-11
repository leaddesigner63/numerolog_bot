import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.bot.handlers import questionnaire


class QuestionnaireEditExistingAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def _run_edit(self, answers: dict[str, str]):
        message = SimpleNamespace(
            bot=AsyncMock(),
            chat=SimpleNamespace(id=100),
        )
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=1, username="tester"),
            message=message,
            answer=AsyncMock(),
        )
        state = AsyncMock()

        question = SimpleNamespace(
            question_id="q1",
            question_type="text",
            text="Как вас зовут?",
            options=[],
            scale=None,
        )
        config = SimpleNamespace(
            version="v1",
            start_question_id="q1",
            questions={"q1": question},
            get_question=lambda question_id: question if question_id == "q1" else None,
        )
        fake_response = SimpleNamespace(answers=answers)

        fake_session = MagicMock()
        fake_session.execute.return_value.scalar_one_or_none.return_value = fake_response

        class _SessionContext:
            def __enter__(self_inner):
                return fake_session

            def __exit__(self_inner, exc_type, exc, tb):
                return False

        with (
            patch.object(questionnaire, "_ensure_paid_access", new=AsyncMock(return_value=True)),
            patch.object(questionnaire, "_ensure_profile_ready", new=AsyncMock(return_value=True)),
            patch.object(questionnaire, "load_questionnaire_config", return_value=config),
            patch.object(questionnaire, "get_session", return_value=_SessionContext()),
            patch.object(questionnaire, "_get_or_create_user", return_value=SimpleNamespace(id=1)),
            patch.object(questionnaire, "_build_actual_answers", return_value=(answers, "q1")),
            patch.object(questionnaire, "_upsert_progress", return_value=SimpleNamespace(
                questionnaire_version="v1",
                status=SimpleNamespace(value="in_progress"),
                answers=answers,
                current_question_id="q1",
                completed_at=None,
            )),
            patch.object(questionnaire, "_update_screen_state"),
            patch.object(questionnaire.screen_manager, "delete_last_question_message", new=AsyncMock()),
            patch.object(questionnaire.screen_manager, "update_last_question_message_id"),
            patch.object(questionnaire.screen_manager, "update_state", return_value=SimpleNamespace(data={})),
        ):
            await questionnaire.edit_questionnaire(callback, state)

        return message.bot.send_message.await_args.kwargs["text"]

    async def test_edit_mode_shows_existing_answer_block(self) -> None:
        sent_text = await self._run_edit({"q1": "Свободный ответ 123"})

        self.assertIn("Текущий ответ:\nСвободный ответ 123", sent_text)
        self.assertIn(
            "чтобы бот подставил текущий ответ в текстовое поле",
            sent_text,
        )
        self.assertIn("Действие: выберите, оставить текущий ответ или изменить.", sent_text)

    async def test_edit_mode_without_existing_answer_hides_block(self) -> None:
        sent_text = await self._run_edit({})

        self.assertIn("Текущий ответ:\n(пусто)", sent_text)
        self.assertIn("Действие: выберите, оставить текущий ответ или изменить.", sent_text)
        self.assertTrue(sent_text.endswith("Как вас зовут?"))


if __name__ == "__main__":
    unittest.main()
