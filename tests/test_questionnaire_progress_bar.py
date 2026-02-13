import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.handlers import questionnaire


class QuestionnaireProgressBarTests(unittest.IsolatedAsyncioTestCase):
    def test_build_questionnaire_progress_bar_renders_expected_values(self) -> None:
        text = questionnaire._build_questionnaire_progress_bar(
            answered_count=3,
            total_questions=10,
        )

        self.assertIn("3/10", text)
        self.assertIn("(30%)", text)

    def test_build_questionnaire_progress_bar_returns_empty_without_total(self) -> None:
        text = questionnaire._build_questionnaire_progress_bar(
            answered_count=2,
            total_questions=0,
        )

        self.assertEqual(text, "")

    async def test_send_question_prepends_progress_bar(self) -> None:
        message = SimpleNamespace(
            bot=AsyncMock(),
            chat=SimpleNamespace(id=123),
        )
        question = SimpleNamespace(
            question_id="q1",
            question_type="text",
            text="Опишите опыт",
            options=[],
            scale=None,
        )

        with patch.object(
            questionnaire.screen_manager,
            "delete_last_question_message",
            new=AsyncMock(),
        ), patch.object(
            questionnaire.screen_manager,
            "enter_text_input_mode",
            new=AsyncMock(),
        ), patch.object(questionnaire.screen_manager, "update_last_question_message_id"):
            await questionnaire._send_question(
                message=message,
                user_id=42,
                question=question,
                answered_count=2,
                total_questions=5,
            )

        kwargs = message.bot.send_message.await_args.kwargs
        self.assertIn("Прогресс анкеты:", kwargs["text"])
        self.assertIn("2/5", kwargs["text"])


if __name__ == "__main__":
    unittest.main()
