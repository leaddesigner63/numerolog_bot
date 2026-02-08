import unittest

from app.bot.handlers.questionnaire import _build_actual_answers
from app.bot.questionnaire.config import load_questionnaire_config


class QuestionnaireActualAnswersTests(unittest.TestCase):
    def test_keeps_only_contiguous_answers(self) -> None:
        config = load_questionnaire_config()
        question_ids = list(config.questions.keys())
        self.assertGreaterEqual(len(question_ids), 3)

        raw_answers = {
            question_ids[0]: "a1",
            question_ids[2]: "a3",
        }

        answers, current_question_id = _build_actual_answers(
            config=config,
            raw_answers=raw_answers,
        )

        self.assertEqual(answers, {question_ids[0]: "a1"})
        self.assertEqual(current_question_id, question_ids[1])

    def test_ignores_stale_tail_answers_when_questionnaire_completed(self) -> None:
        config = load_questionnaire_config()
        question_ids = list(config.questions.keys())
        raw_answers = {question_id: f"ans-{index}" for index, question_id in enumerate(question_ids, start=1)}
        raw_answers["deprecated-question"] = "stale"

        answers, current_question_id = _build_actual_answers(
            config=config,
            raw_answers=raw_answers,
        )

        expected_answers = {
            question_id: f"ans-{index}" for index, question_id in enumerate(question_ids, start=1)
        }
        self.assertEqual(answers, expected_answers)
        self.assertIsNone(current_question_id)


if __name__ == "__main__":
    unittest.main()
