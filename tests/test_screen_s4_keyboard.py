import unittest

from app.bot.screens import screen_s4


class ScreenS4KeyboardTests(unittest.TestCase):
    def test_hides_inline_keyboard_when_redirect_after_paid_payment(self) -> None:
        content = screen_s4(
            {
                "selected_tariff": "T1",
                "order_status": "paid",
                "profile": {
                    "name": "Тест",
                    "birth_date": "01.01.2000",
                    "birth_time": "10:00",
                    "birth_place": {"city": "Москва", "region": "", "country": ""},
                },
                "s4_no_inline_keyboard": True,
            }
        )

        self.assertIsNone(content.keyboard)

    def test_t1_uses_custom_tariff_title_in_intro(self) -> None:
        content = screen_s4({"selected_tariff": "T1"})

        self.assertIn("Мои данные для тарифа В чём твоя сила?.", content.messages[0])

    def test_profile_flow_with_profile_shows_only_three_buttons(self) -> None:
        content = screen_s4(
            {
                "selected_tariff": "T1",
                "order_status": "paid",
                "profile_flow": True,
                "profile": {
                    "name": "Тест",
                    "gender": "Женский",
                    "birth_date": "01.01.2000",
                    "birth_time": "10:00",
                    "birth_place": {"city": "Москва", "region": "", "country": ""},
                },
            }
        )

        self.assertIsNotNone(content.keyboard)
        rows = content.keyboard.inline_keyboard
        labels = [button.text for row in rows for button in row]

        self.assertEqual(
            labels,
            [
                "📝 Редактировать",
                "🗑️ Удалить мои данные",
                "✅ Продолжить",
            ],
        )
        self.assertNotIn("👤 Кабинет", labels)
        self.assertNotIn("➡️ Тарифы", labels)


if __name__ == "__main__":
    unittest.main()
