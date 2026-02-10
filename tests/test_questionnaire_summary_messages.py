import unittest
from types import SimpleNamespace

from app.bot.handlers.questionnaire import _build_answers_summary_messages


class QuestionnaireSummaryMessagesTests(unittest.TestCase):
    def test_build_summary_keeps_config_order_and_empty_answers(self) -> None:
        config = SimpleNamespace(
            questions={
                "q1": SimpleNamespace(question_id="q1", text="Первый вопрос?"),
                "q2": SimpleNamespace(question_id="q2", text="Второй вопрос?"),
                "q3": SimpleNamespace(question_id="q3", text="Третий вопрос?"),
            }
        )

        messages = _build_answers_summary_messages(
            config=config,
            answers={"q2": "Ответ 2"},
            max_length=4096,
        )

        self.assertEqual(len(messages), 1)
        self.assertEqual(
            messages[0],
            "1. Первый вопрос?\n"
            "Текущий ответ: (пусто)\n\n"
            "2. Второй вопрос?\n"
            "Текущий ответ: Ответ 2\n\n"
            "3. Третий вопрос?\n"
            "Текущий ответ: (пусто)",
        )

    def test_build_summary_splits_long_block(self) -> None:
        long_answer = "А" * 100
        config = SimpleNamespace(
            questions={
                "q1": SimpleNamespace(question_id="q1", text="Очень длинный вопрос?"),
            }
        )

        messages = _build_answers_summary_messages(
            config=config,
            answers={"q1": long_answer},
            max_length=40,
        )

        self.assertGreater(len(messages), 1)
        self.assertEqual("".join(messages), f"1. Очень длинный вопрос?\nТекущий ответ: {long_answer}")


if __name__ == "__main__":
    unittest.main()
