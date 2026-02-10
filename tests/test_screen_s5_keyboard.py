import unittest

from app.bot.screens import screen_s5


class ScreenS5KeyboardTests(unittest.TestCase):
    def _button_texts(self, *, state: dict) -> list[str]:
        content = screen_s5(state)
        keyboard = content.keyboard
        self.assertIsNotNone(keyboard)
        return [button.text for row in keyboard.inline_keyboard for button in row]

    def test_empty_questionnaire_shows_fill_button_even_for_paid_order(self) -> None:
        texts = self._button_texts(
            state={
                "order_id": "42",
                "order_status": "paid",
                "questionnaire": {
                    "status": "empty",
                    "answered_count": 0,
                    "total_questions": 5,
                },
            }
        )

        self.assertTrue(any("Заполнить анкету" in text for text in texts))

    def test_in_progress_questionnaire_shows_continue_questionnaire(self) -> None:
        texts = self._button_texts(
            state={
                "order_id": "42",
                "order_status": "paid",
                "questionnaire": {
                    "status": "in_progress",
                    "answered_count": 2,
                    "total_questions": 5,
                },
            }
        )

        self.assertTrue(any("Продолжить анкету" in text for text in texts))

    def test_completed_questionnaire_keeps_edit_and_done_actions(self) -> None:
        texts = self._button_texts(
            state={
                "order_id": "42",
                "order_status": "paid",
                "questionnaire": {
                    "status": "completed",
                    "answered_count": 5,
                    "total_questions": 5,
                },
            }
        )

        self.assertTrue(any("Редактировать анкету" in text for text in texts))
        self.assertTrue(any("Редактировать данные" in text for text in texts))
        self.assertTrue(any("Готово" in text for text in texts))


if __name__ == "__main__":
    unittest.main()
