import unittest
from types import SimpleNamespace

from app.bot.handlers.questionnaire import _build_answers_summary_messages


class QuestionnaireSummaryMessagesTests(unittest.TestCase):
    def test_build_summary_keeps_config_order_and_empty_answers(self) -> None:
        config = SimpleNamespace(
            questions={
                "q1": SimpleNamespace(question_id="q1", text="Какие задачи у вас получаются лучше всего?"),
                "q2": SimpleNamespace(question_id="q2", text="В каких навыках вы уверены сейчас?"),
                "q3": SimpleNamespace(question_id="q3", text="Что вас сейчас сильнее всего мотивирует?"),
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
            "1. Какие задачи у вас получаются лучше всего?\n"
            "Текущий ответ: (пусто)\n\n"
            "2. В каких навыках вы уверены сейчас?\n"
            "Текущий ответ: Ответ 2\n\n"
            "3. Что вас сейчас сильнее всего мотивирует?\n"
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
