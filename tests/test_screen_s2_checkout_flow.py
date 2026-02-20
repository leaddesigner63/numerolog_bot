import unittest

from app.bot.screens import screen_s2, screen_s2_details


class ScreenS2CheckoutFlowTests(unittest.TestCase):
    def test_paid_tariff_description_hides_price_until_checkout(self) -> None:
        content = screen_s2({"selected_tariff": "T1"})

        self.assertNotIn("Стоимость:", content.messages[0])
        self.assertNotIn("оплат", content.messages[0].lower())
        self.assertNotIn("Перед следующим шагом:", content.messages[0])
        self.assertNotIn(
            "Сервис не является консультацией, прогнозом или рекомендацией к действию.",
            content.messages[0],
        )
        buttons = content.keyboard.inline_keyboard if content.keyboard else []
        callbacks = [button.callback_data for row in buttons for button in row if button.callback_data]
        self.assertIn("screen:S4", callbacks)
        self.assertIn("s2:details", callbacks)
        self.assertNotIn("screen:S3", callbacks)

    def test_details_screen_contains_long_description(self) -> None:
        content = screen_s2_details({"selected_tariff": "T2"})

        self.assertIn("анализирует тебя с упором на доход", content.messages[0])
        buttons = content.keyboard.inline_keyboard if content.keyboard else []
        callbacks = [button.callback_data for row in buttons for button in row if button.callback_data]
        self.assertIn("s2:details:back", callbacks)
        self.assertIn("s2:details:continue", callbacks)


if __name__ == "__main__":
    unittest.main()
