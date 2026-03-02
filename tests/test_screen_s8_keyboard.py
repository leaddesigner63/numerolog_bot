import unittest

from app.bot import screens


class ScreenS8KeyboardTests(unittest.TestCase):
    def test_s8_has_no_inline_keyboard_while_waiting_text_input(self) -> None:
        content = screens.screen_s8({})
        self.assertIsNone(content.keyboard)

    def test_s8_manual_payment_receipt_text(self) -> None:
        content = screens.screen_s8({"s8_context": "manual_payment_receipt"})
        self.assertIn("Отправьте скриншот оплаты", content.messages[0])
        self.assertNotIn("обожают ваши отзывы", content.messages[0])


if __name__ == "__main__":
    unittest.main()
