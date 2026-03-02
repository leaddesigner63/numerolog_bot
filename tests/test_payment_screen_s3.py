import unittest

from app.bot.screens import screen_s15, screen_s3, screen_s3_report_details
from app.core.config import settings


class PaymentScreenS3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_payment_mode = getattr(settings, "payment_mode", "provider")
        self.original_manual_payment_card_number = getattr(settings, "manual_payment_card_number", None)
        self.original_manual_payment_recipient_name = getattr(settings, "manual_payment_recipient_name", None)
        self.original_feedback_group_url = getattr(settings, "feedback_group_url", None)

    def tearDown(self) -> None:
        settings.payment_mode = self.original_payment_mode
        settings.manual_payment_card_number = self.original_manual_payment_card_number
        settings.manual_payment_recipient_name = self.original_manual_payment_recipient_name
        settings.feedback_group_url = self.original_feedback_group_url

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
        self.assertIn("Шаг 3. Подтверждение оплаты", message)
        self.assertIn("Тариф:", message)
        self.assertIn("Стоимость: 560 RUB", message)
        self.assertIn("Сразу после оплаты вы получите доступ к персональному отчёту", message)
        self.assertIn("Формат результата: PDF", message)
        self.assertNotIn("Без гарантий результата", message)
        self.assertIn("Нажмите «Оплатить», чтобы перейти к оплате", message)
        self.assertIn("Без подписки и автосписаний", message)
        self.assertNotIn("Что входит в отчёт", message)
        self.assertNotIn("Юридическая информация", message)

        keyboard_rows = content.keyboard.inline_keyboard if content.keyboard else []
        self.assertGreaterEqual(len(keyboard_rows), 1)
        self.assertEqual(keyboard_rows[0][0].url, "https://example.com/pay")
        self.assertIn("Оплатить", keyboard_rows[0][0].text)
        self.assertEqual(keyboard_rows[1][0].callback_data, "screen:S4")

    def test_s3_falls_back_to_settings_price_when_order_amount_missing(self) -> None:
        content = screen_s3({"selected_tariff": "T1", "payment_url": "https://example.com/pay"})
        expected_price = settings.tariff_prices_rub.get("T1")
        self.assertIn(f"Стоимость: {expected_price} RUB", content.messages[0])


    def test_s3_displays_plain_price_without_spoiler_for_all_paid_tariffs(self) -> None:
        for tariff in ("T1", "T2", "T3"):
            content = screen_s3({"selected_tariff": tariff, "payment_url": "https://example.com/pay"})
            message = content.messages[0]
            self.assertIn("Стоимость:", message)
            self.assertNotIn("||", message)

    def test_s3_shows_start_payment_callback_when_order_not_created_yet(self) -> None:
        content = screen_s3({"selected_tariff": "T1"})

        buttons = []
        if content.keyboard and content.keyboard.inline_keyboard:
            for row in content.keyboard.inline_keyboard:
                for button in row:
                    buttons.append((button.text, button.callback_data, button.url))

        callback_values = {callback for _, callback, _ in buttons if callback}
        fallback_payment_buttons = [
            text for text, callback, _ in buttons if callback == "payment:start"
        ]
        url_values = {url for _, _, url in buttons if url}
        self.assertIn("payment:start", callback_values)
        self.assertTrue(any("Перейти к оплате" in text for text in fallback_payment_buttons))
        self.assertNotIn("https://example.com/pay", url_values)
        self.assertNotIn("s3:report_details", callback_values)
        self.assertNotIn("legal:offer", callback_values)

    def test_s3_falls_back_to_provider_mode_for_unknown_payment_mode(self) -> None:
        settings.payment_mode = "unexpected_mode"

        content = screen_s3({"selected_tariff": "T1", "payment_url": "https://example.com/pay"})

        keyboard_rows = content.keyboard.inline_keyboard if content.keyboard else []
        self.assertEqual(keyboard_rows[0][0].url, "https://example.com/pay")

    def test_s3_manual_mode_without_card_shows_support_cta(self) -> None:
        settings.payment_mode = "manual"
        settings.manual_payment_card_number = None
        settings.feedback_group_url = "https://t.me/example_support"

        content = screen_s3({"selected_tariff": "T1", "payment_url": "https://example.com/pay"})

        self.assertIn("Реквизиты временно недоступны, напишите в поддержку", content.messages[0])
        keyboard_rows = content.keyboard.inline_keyboard if content.keyboard else []
        self.assertEqual(keyboard_rows[0][0].url, "https://t.me/example_support")
        self.assertIn("Написать в поддержку", keyboard_rows[0][0].text)

    def test_s3_manual_mode_with_card_shows_requisites(self) -> None:
        settings.payment_mode = "manual"
        settings.manual_payment_card_number = "2200 7000 1234 5678"
        settings.manual_payment_recipient_name = "Иван Иванов"

        content = screen_s3({"selected_tariff": "T1"})

        self.assertIn("Оплата сейчас принимается по ручным реквизитам", content.messages[0])
        self.assertIn("Тариф:", content.messages[0])
        self.assertIn("Стоимость:", content.messages[0])
        self.assertIn("2200 7000 1234 5678", content.messages[0])
        self.assertIn("Иван Иванов", content.messages[0])
        self.assertIn("После оплаты отправьте скриншот чека в этот чат", content.messages[0])
        self.assertIn("Отчёт будет готов в течение 15 минут", content.messages[0])

        keyboard_rows = content.keyboard.inline_keyboard if content.keyboard else []
        self.assertEqual(keyboard_rows[0][0].callback_data, "screen:S8")
        self.assertIn("Я оплатил(а), отправить скрин", keyboard_rows[0][0].text)

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

    def test_s3_shows_continue_button_when_order_already_paid(self) -> None:
        content = screen_s3(
            {
                "selected_tariff": "T1",
                "order_id": "42",
                "order_status": "paid",
                "order_amount": "560",
                "order_currency": "RUB",
                "payment_url": "https://example.com/pay",
            }
        )

        buttons = []
        if content.keyboard and content.keyboard.inline_keyboard:
            for row in content.keyboard.inline_keyboard:
                for button in row:
                    buttons.append((button.text, button.callback_data, button.url))

        callback_values = {callback for _, callback, _ in buttons if callback}
        url_values = {url for _, _, url in buttons if url}

        self.assertIn("payment:paid", callback_values)
        self.assertNotIn("https://example.com/pay", url_values)


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
        self.assertNotIn("Дисклеймер:", content.messages[0])
        self.assertIsNone(content.keyboard)


    def test_s3_report_details_screen_keeps_checkout_context(self) -> None:
        content = screen_s3_report_details(
            {
                "selected_tariff": "T2",
                "order_id": "77",
                "order_status": "created",
            }
        )

        message = content.messages[0]
        self.assertIn("Что входит в отчёт", message)
        self.assertIn("Сразу после оплаты", message)
        self.assertIn("Формат: PDF", message)
        self.assertIn("Прозрачность: сервис не гарантирует конкретный результат", message)
        self.assertIn("Юридическая информация", message)
        self.assertIn("Оплата подтверждает согласие с офертой", message)
        self.assertIn("Заказ №77", message)
        self.assertIn("Где твои деньги?", message)

        keyboard_rows = content.keyboard.inline_keyboard if content.keyboard else []
        self.assertEqual(keyboard_rows[0][0].callback_data, "s3:report_details:back")

    def test_s3_report_details_shows_manual_sla_in_manual_mode(self) -> None:
        settings.payment_mode = "manual"

        content = screen_s3_report_details({"selected_tariff": "T1"})

        self.assertIn("Отчёт будет готов в течение 15 минут после подтверждения оплаты", content.messages[0])

    def test_s3_back_button_targets_s4_by_default(self) -> None:
        content = screen_s3({"selected_tariff": "T1", "payment_url": "https://example.com/pay"})

        keyboard_rows = content.keyboard.inline_keyboard if content.keyboard else []
        back_button = keyboard_rows[1][0]
        self.assertEqual(back_button.callback_data, "screen:S4")

    def test_s3_back_button_uses_explicit_back_target(self) -> None:
        content = screen_s3(
            {
                "selected_tariff": "T2",
                "payment_url": "https://example.com/pay",
                "s3_back_target": "S5",
            }
        )

        keyboard_rows = content.keyboard.inline_keyboard if content.keyboard else []
        back_button = keyboard_rows[1][0]
        self.assertEqual(back_button.callback_data, "screen:S5")


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
