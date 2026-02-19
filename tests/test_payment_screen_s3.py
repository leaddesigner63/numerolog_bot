import unittest

from app.bot.screens import screen_s15, screen_s3
from app.core.config import settings


class PaymentScreenS3Tests(unittest.TestCase):
    def test_s3_shows_tariff_price_disclaimer_and_payment_button(self) -> None:
        content = screen_s3(
            {
                "selected_tariff": "T1",
                "order_amount": "560",
                "order_currency": "RUB",
                "payment_url": "https://example.com/pay",
            }
        )

        message = content.messages[0]
        self.assertIn("Финальный шаг перед генерацией отчёта", message)
        self.assertIn("Тариф:", message)
        self.assertIn("Стоимость: 560 RUB", message)
        self.assertIn("Короткий дисклеймер", message)
        self.assertIn("Оплачивая, вы подтверждаете согласие", message)

        keyboard_rows = content.keyboard.inline_keyboard if content.keyboard else []
        self.assertGreaterEqual(len(keyboard_rows), 1)
        self.assertEqual(keyboard_rows[0][0].url, "https://example.com/pay")

    def test_s3_falls_back_to_settings_price_when_order_amount_missing(self) -> None:
        content = screen_s3({"selected_tariff": "T1", "payment_url": "https://example.com/pay"})
        expected_price = settings.tariff_prices_rub.get("T1")
        self.assertIn(f"Стоимость: {expected_price} RUB", content.messages[0])

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


    def test_s3_shows_processing_notice_when_returned_from_payment_form(self) -> None:
        content = screen_s3(
            {
                "selected_tariff": "T1",
                "order_id": "42",
                "order_status": "created",
                "order_amount": "560",
                "order_currency": "RUB",
                "payment_url": "https://example.com/pay",
                "payment_processing_notice": True,
            }
        )

        self.assertIn("Платеж обрабатывается, пожалуйста подождите.", content.messages[0])
        self.assertNotIn("Стоимость:", content.messages[0])
        self.assertNotIn("Короткий дисклеймер", content.messages[0])
        self.assertIsNone(content.keyboard)


class PaymentScreenS15Tests(unittest.TestCase):
    def test_s15_shows_only_reports_for_current_tariff(self) -> None:
        content = screen_s15(
            {
                "selected_tariff": "T2",
                "reports": [
                    {"id": "1", "tariff": "T1", "created_at": "2025-01-01"},
                    {"id": "2", "tariff": "T2", "created_at": "2025-01-02"},
                    {"id": "3", "tariff": "T3", "created_at": "2025-01-03"},
                ],
                "reports_total": 3,
            }
        )

        message = content.messages[0]
        self.assertIn("Отчёт #2", message)
        self.assertNotIn("Отчёт #1", message)
        self.assertNotIn("Отчёт #3", message)

    def test_s15_shows_payment_button_first_with_short_label(self) -> None:
        content = screen_s15({"selected_tariff": "T1", "reports": [], "reports_total": 0})

        keyboard_rows = content.keyboard.inline_keyboard if content.keyboard else []
        self.assertGreaterEqual(len(keyboard_rows), 2)
        self.assertEqual(keyboard_rows[0][0].callback_data, "existing_report:continue")
        self.assertIn("К оплате", keyboard_rows[0][0].text)
        self.assertEqual(keyboard_rows[1][0].callback_data, "existing_report:lk")
        self.assertIn("Перейти в ЛК", keyboard_rows[1][0].text)
        self.assertNotIn("Продолжить к оплате", keyboard_rows[0][0].text)


if __name__ == "__main__":
    unittest.main()
