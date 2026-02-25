import unittest

from app.bot.screens import screen_s5


class ScreenS5KeyboardTests(unittest.TestCase):
    def _button_texts(self, *, state: dict) -> list[str]:
        content = screen_s5(state)
        keyboard = content.keyboard
        self.assertIsNotNone(keyboard)
        return [button.text for row in keyboard.inline_keyboard for button in row]

    def test_paid_order_shows_continue_button(self) -> None:
        texts = self._button_texts(
            state={
                "order_id": "42",
                "order_status": "paid",
                "questionnaire": {
                    "status": "in_progress",
                    "answered_count": 0,
                    "total_questions": 5,
                },
            }
        )

        self.assertEqual(texts[0], "✅ Продолжить")
        self.assertFalse(any("Заполнить анкету" in text for text in texts))
        self.assertTrue(any("Редактировать анкету" in text for text in texts))
        self.assertFalse(any("Редактировать данные" in text for text in texts))

    def test_paid_order_empty_questionnaire_shows_full_keyboard(self) -> None:
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

        self.assertEqual(texts[0], "✅ Продолжить")
        self.assertTrue(any("Редактировать анкету" in text for text in texts))
        self.assertFalse(any("Редактировать данные" in text for text in texts))

    def test_unpaid_order_shows_fill_questionnaire_button(self) -> None:
        texts = self._button_texts(
            state={
                "order_id": "42",
                "order_status": "created",
                "questionnaire": {
                    "status": "empty",
                    "answered_count": 0,
                    "total_questions": 5,
                },
            }
        )

        self.assertEqual(texts[0], "📝 Заполнить анкету")


if __name__ == "__main__":
    unittest.main()
