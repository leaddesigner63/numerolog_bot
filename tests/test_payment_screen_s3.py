import unittest

from app.bot.screens import screen_s3


class PaymentScreenS3Tests(unittest.TestCase):
    def test_s3_has_no_manual_payment_confirmation_button(self) -> None:
        content = screen_s3(
            {
                "selected_tariff": "T1",
                "order_id": "42",
                "order_status": "created",
                "order_amount": "560",
                "order_currency": "RUB",
                "payment_url": "https://example.com/pay",
            }
        )

        buttons = []
        if content.keyboard and content.keyboard.inline_keyboard:
            for row in content.keyboard.inline_keyboard:
                for button in row:
                    buttons.append((button.text, button.callback_data))

        callback_values = {callback for _, callback in buttons if callback}
        self.assertNotIn("payment:paid", callback_values)


if __name__ == "__main__":
    unittest.main()
