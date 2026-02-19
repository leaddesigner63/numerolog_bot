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

        self.assertIn("Мои данные.", content.messages[0])

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


    def test_profile_not_filled_text_starts_with_payment_success_banner(self) -> None:
        content = screen_s4(
            {
                "selected_tariff": "T1",
                "order_status": "paid",
                "profile_flow": "report",
            }
        )

        self.assertIn("🟧 ОПЛАТА ПРОШЛА УСПЕШНО. 🟧", content.messages[0])
        self.assertIn("\n\nМои данные.", content.messages[0])
        self.assertIn("Данные ещё не заполнены.", content.messages[0])

    def test_profile_text_starts_with_payment_success_banner(self) -> None:
        content = screen_s4(
            {
                "selected_tariff": "T1",
                "order_status": "paid",
                "profile_flow": "report",
                "profile": {
                    "name": "Тест",
                    "gender": "Мужской",
                    "birth_date": "31.12.1988",
                    "birth_time": "21:30",
                    "birth_place": {
                        "city": "Макеевка",
                        "region": "Донецкая область",
                        "country": "СССР",
                    },
                },
            }
        )

        self.assertIn("🟧 ОПЛАТА ПРОШЛА УСПЕШНО. 🟧", content.messages[0])
        self.assertIn("\n\nМои данные:", content.messages[0])

    def test_profile_text_from_cabinet_hides_payment_success_banner(self) -> None:
        content = screen_s4(
            {
                "selected_tariff": "T1",
                "order_status": "paid",
                "profile": {
                    "name": "Тест",
                    "gender": "Мужской",
                    "birth_date": "31.12.1988",
                    "birth_time": "21:30",
                    "birth_place": {
                        "city": "Макеевка",
                        "region": "Донецкая область",
                        "country": "СССР",
                    },
                },
            }
        )

        self.assertNotIn("🟧 ОПЛАТА ПРОШЛА УСПЕШНО. 🟧", content.messages[0])

    def test_paid_tariff_with_profile_shows_continue_even_without_profile_flow(self) -> None:
        content = screen_s4(
            {
                "selected_tariff": "T2",
                "order_status": "paid",
                "profile": {
                    "name": "Тест",
                    "gender": "Мужской",
                    "birth_date": "31.12.1988",
                    "birth_time": "21:30",
                    "birth_place": {
                        "city": "Макеевка",
                        "region": "Донецкая область",
                        "country": "СССР",
                    },
                },
            }
        )

        self.assertIsNotNone(content.keyboard)
        labels = [button.text for row in content.keyboard.inline_keyboard for button in row]

        self.assertIn("✅ Продолжить", labels)
        self.assertIn("👤 Кабинет", labels)
        self.assertIn("➡️ Тарифы", labels)

    def test_t0_with_profile_shows_continue_button(self) -> None:
        content = screen_s4(
            {
                "selected_tariff": "T0",
                "profile": {
                    "name": "Тест",
                    "gender": "Мужской",
                    "birth_date": "31.12.1988",
                    "birth_time": "21:30",
                    "birth_place": {
                        "city": "Макеевка",
                        "region": "Донецкая область",
                        "country": "СССР",
                    },
                },
            }
        )

        self.assertIsNotNone(content.keyboard)
        labels = [button.text for row in content.keyboard.inline_keyboard for button in row]

        self.assertIn("✅ Продолжить", labels)
        self.assertIn("👤 Кабинет", labels)
        self.assertIn("➡️ Тарифы", labels)


if __name__ == "__main__":
    unittest.main()
