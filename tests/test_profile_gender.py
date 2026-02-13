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



    def test_screen_s11_has_questionnaire_edit_button(self) -> None:
        content = screen_s11(
            {
                "questionnaire": {
                    "status": "completed",
                }
            }
        )

        callback_data = [
            button.callback_data
            for row in content.keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertIn("questionnaire:edit:lk", callback_data)

    def test_screen_s11_shows_questionnaire_delete_button_when_not_empty(self) -> None:
        content = screen_s11(
            {
                "questionnaire": {
                    "status": "in_progress",
                }
            }
        )

        callback_data = [
            button.callback_data
            for row in content.keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertIn("questionnaire:delete:lk", callback_data)


    def test_screen_s11_shows_expand_answers_button_for_long_answers(self) -> None:
        content = screen_s11(
            {
                "questionnaire": {
                    "status": "completed",
                    "answers": {
                        "Цели": "А" * 300,
                    },
                }
            }
        )

        callback_data = [
            button.callback_data
            for row in content.keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertIn("questionnaire:answers:expand", callback_data)

    def test_screen_s11_shows_collapse_answers_button_when_expanded(self) -> None:
        content = screen_s11(
            {
                "questionnaire_answers_expanded": True,
                "questionnaire": {
                    "status": "completed",
                    "answers": {
                        "Цели": "А" * 300,
                    },
                },
            }
        )

        callback_data = [
            button.callback_data
            for row in content.keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertIn("questionnaire:answers:collapse", callback_data)

    def test_screen_s11_hides_questionnaire_delete_button_when_empty(self) -> None:
        content = screen_s11(
            {
                "questionnaire": {
                    "status": "empty",
                }
            }
        )

        callback_data = [
            button.callback_data
            for row in content.keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertNotIn("questionnaire:delete:lk", callback_data)

if __name__ == "__main__":
    unittest.main()
