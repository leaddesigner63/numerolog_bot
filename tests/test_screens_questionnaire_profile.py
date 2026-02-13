import unittest

from app.bot.screens import _format_questionnaire_profile


class ScreensQuestionnaireProfileTests(unittest.TestCase):
    def test_uses_question_text_for_russian_question_ids_from_config(self) -> None:
        text = _format_questionnaire_profile(
            {
                "status": "completed",
                "version": "v1",
                "answered_count": 5,
                "total_questions": 5,
                "completed_at": "2026-02-07T06:16:32.968721+00:00",
                "answers": {
                    "Ваш опыт": "Опытный",
                    "Уровень уверенности в навыках": "4/5",
                    "Цели": "Рост дохода",
                },
            }
        )

        self.assertIn("• Статус: завершена", text)
        self.assertIn("• Завершена: 07.02.2026 06:16", text)
        self.assertIn(
            "1. Опишите ваш опыт: проекты, роли или задачи, которые давались лучше всего.\n   Опытный",
            text,
        )
        self.assertIn(
            "2. Опишите уровень уверенности в ключевых навыках в свободной форме (любые формулировки).\n   4/5",
            text,
        )
        self.assertIn(
            "3. Сформулируйте ваши цели на ближайшие 6–12 месяцев.\n   Рост дохода",
            text,
        )

    def test_falls_back_to_original_key_and_truncates_long_answer_by_default(self) -> None:
        long_answer = "А" * 500
        text = _format_questionnaire_profile(
            {
                "status": "in_progress",
                "version": "v1",
                "answered_count": 1,
                "total_questions": 5,
                "completed_at": None,
                "answers": {
                    "Произвольный ключ": long_answer,
                },
            }
        )

        self.assertIn("1. Произвольный ключ", text)
        self.assertIn("…", text)
        self.assertNotIn("\n   " + long_answer, text)

    def test_shows_full_long_answer_when_expanded(self) -> None:
        long_answer = "А" * 500
        text = _format_questionnaire_profile(
            {
                "status": "in_progress",
                "version": "v1",
                "answered_count": 1,
                "total_questions": 5,
                "completed_at": None,
                "answers": {
                    "Произвольный ключ": long_answer,
                },
            },
            expanded_answers=True,
        )

        self.assertIn("1. Произвольный ключ\n   " + long_answer, text)

    def test_hides_bot_mention_prefix_in_answers(self) -> None:
        text = _format_questionnaire_profile(
            {
                "status": "completed",
                "version": "v1",
                "answered_count": 1,
                "total_questions": 5,
                "completed_at": "2026-02-07T06:16:32.968721+00:00",
                "answers": {
                    "Цели": "@AlreadyUbot хочу роста и движения",
                },
            }
        )

        self.assertIn("1. Сформулируйте ваши цели на ближайшие 6–12 месяцев.", text)
        self.assertIn("   хочу роста и движения", text)
        self.assertNotIn("@AlreadyUbot", text)


if __name__ == "__main__":
    unittest.main()
