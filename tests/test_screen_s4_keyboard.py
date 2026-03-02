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

        self.assertIn("Шаг 4. Заполните профиль", content.messages[0])

    def test_profile_flow_with_profile_hides_delete_and_cabinet_buttons(self) -> None:
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

        self.assertEqual(labels[0], "✅ Продолжить")
        self.assertEqual(labels[1], "📝 Редактировать")
        self.assertNotIn("🗑️ Удалить мои данные", labels)
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

        self.assertIn("⚠️ ОПЛАТА ПРОШЛА УСПЕШНО.", content.messages[0])
        self.assertIn("Шаг 4. Заполните профиль", content.messages[0])
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

        self.assertIn("⚠️ ОПЛАТА ПРОШЛА УСПЕШНО.", content.messages[0])
        self.assertIn("Шаг 4. Проверьте данные профиля", content.messages[0])

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

        self.assertNotIn("⚠️ ОПЛАТА ПРОШЛА УСПЕШНО.", content.messages[0])

    def test_paid_tariff_with_profile_hides_delete_and_cabinet_in_order_flow(self) -> None:
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
        self.assertNotIn("🗑️ Удалить мои данные", labels)
        self.assertNotIn("👤 Кабинет", labels)
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

    def test_paid_tariff_with_profile_shows_continue_when_order_status_missing(self) -> None:
        content = screen_s4(
            {
                "selected_tariff": "T3",
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

    def test_unpaid_tariff_shows_single_tariffs_button(self) -> None:
        content = screen_s4({"selected_tariff": "T1", "order_status": "pending"})

        self.assertIsNotNone(content.keyboard)
        labels = [button.text for row in content.keyboard.inline_keyboard for button in row]

        self.assertEqual(labels.count("🧾 Тарифы"), 1)
        self.assertEqual(labels.count("➡️ Тарифы"), 0)
        self.assertEqual(labels[0], "💳 Перейти к оплате")

    def test_t2_with_incomplete_questionnaire_shows_cta_to_s5(self) -> None:
        content = screen_s4(
            {
                "selected_tariff": "T2",
                "order_status": "pending",
                "questionnaire": {"status": "in_progress", "answers": {"q1": "ответ"}},
            }
        )

        self.assertIsNotNone(content.keyboard)
        primary_button = content.keyboard.inline_keyboard[0][0]
        self.assertEqual(primary_button.callback_data, "screen:S5")
        self.assertEqual(primary_button.text, "▶️ Продолжить анкету")

    def test_t3_with_completed_questionnaire_shows_cta_to_s3(self) -> None:
        content = screen_s4(
            {
                "selected_tariff": "T3",
                "order_status": "pending",
                "questionnaire": {"status": "completed"},
            }
        )

        self.assertIsNotNone(content.keyboard)
        primary_button = content.keyboard.inline_keyboard[0][0]
        self.assertEqual(primary_button.callback_data, "screen:S3")
        self.assertEqual(primary_button.text, "💳 Перейти к оплате")

    def test_t1_without_questionnaire_keeps_cta_to_s3(self) -> None:
        content = screen_s4(
            {
                "selected_tariff": "T1",
                "order_status": "pending",
                "questionnaire": {"status": "in_progress"},
            }
        )

        self.assertIsNotNone(content.keyboard)
        primary_button = content.keyboard.inline_keyboard[0][0]
        self.assertEqual(primary_button.callback_data, "screen:S3")
        self.assertEqual(primary_button.text, "💳 Перейти к оплате")


if __name__ == "__main__":
    unittest.main()
