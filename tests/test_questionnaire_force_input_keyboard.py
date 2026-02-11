import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.handlers import questionnaire


class QuestionnaireForceInputKeyboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_force_input_for_text_question_has_no_copy_button(self) -> None:
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
        ), patch.object(questionnaire.screen_manager, "update_last_question_message_id"):
            await questionnaire._send_question(
                message=message,
                user_id=42,
                question=question,
                existing_answer="Текущий ответ",
                force_input=True,
            )

        kwargs = message.bot.send_message.await_args.kwargs
        self.assertIsNone(kwargs["reply_markup"])
        self.assertNotIn("Редактировать текущий ответ", kwargs["text"])


if __name__ == "__main__":
    unittest.main()
