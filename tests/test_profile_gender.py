import unittest

from app.bot.screens import screen_s4, screen_s4_edit, screen_s11
from app.core.report_service import ReportService


class ProfileGenderTests(unittest.TestCase):
    def test_screen_s4_shows_gender_in_profile(self) -> None:
        content = screen_s4(
            {
                "selected_tariff": "T1",
                "profile": {
                    "name": "Алекс",
                    "gender": "небинарный",
                    "birth_date": "01.01.2000",
                    "birth_time": "10:00",
                    "birth_place": {"city": "Москва", "region": "", "country": ""},
                },
            }
        )

        self.assertIn("Пол: небинарный", content.messages[0])

    def test_screen_s4_edit_has_gender_button(self) -> None:
        content = screen_s4_edit(
            {
                "profile": {
                    "name": "Алекс",
                    "gender": "любой",
                    "birth_date": "01.01.2000",
                    "birth_time": "10:00",
                    "birth_place": {"city": "Москва", "region": "", "country": ""},
                }
            }
        )

        callback_data = [
            button.callback_data
            for row in content.keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertIn("profile:edit:gender", callback_data)

    def test_report_facts_pack_includes_gender(self) -> None:
        service = ReportService()
        facts = service._build_facts_pack(
            user_id=123,
            state={
                "selected_tariff": "T2",
                "profile": {
                    "name": "Тест",
                    "gender": "женский",
                    "birth_date": "01.01.2000",
                    "birth_time": "10:00",
                    "birth_place": {"city": "Москва", "region": None, "country": ""},
                },
                "questionnaire": {},
            },
        )

        self.assertEqual(facts["profile"]["gender"], "женский")

    def test_screen_s11_shows_gender(self) -> None:
        content = screen_s11(
            {
                "profile": {
                    "name": "Алекс",
                    "gender": "мужской",
                    "birth_date": "01.01.2000",
                    "birth_time": "10:00",
                    "birth_place": {"city": "Москва", "region": "", "country": ""},
                }
            }
        )

        self.assertIn("Пол: мужской", content.messages[0])


if __name__ == "__main__":
    unittest.main()
