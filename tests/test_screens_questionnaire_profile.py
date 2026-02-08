import unittest

from app.bot.screens import _format_questionnaire_profile


class ScreensQuestionnaireProfileTests(unittest.TestCase):
    def test_translates_status_and_answer_fields_to_russian(self) -> None:
        text = _format_questionnaire_profile(
            {
                "status": "completed",
                "version": "v1",
                "answered_count": 5,
                "total_questions": 5,
                "completed_at": "2026-02-07T06:16:32.968721+00:00",
                "answers": {
                    "experience": "Опытный",
                    "skills": "4/5",
                    "interests": "Деньги",
                },
            }
        )

        self.assertIn("Статус: завершена", text)
        self.assertIn("- Навыки: 4/5", text)
        self.assertIn("- Интересы: Деньги", text)


if __name__ == "__main__":
    unittest.main()
