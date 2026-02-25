import unittest

from app.bot.handlers.screen_manager import ScreenManager


class ScreenMessageLengthsTests(unittest.TestCase):
    def test_s0_to_s7_messages_fit_telegram_single_message_limit(self) -> None:
        manager = ScreenManager()
        scenarios = {
            "S0": {},
            "S1": {},
            "S2": {"selected_tariff": "T1"},
            "S3": {"selected_tariff": "T1", "payment_url": "https://example.com/pay"},
            "S4": {
                "selected_tariff": "T1",
                "profile": {
                    "name": "Тест",
                    "gender": "Женский",
                    "birth_date": "01.01.1990",
                    "birth_time": "09:30",
                    "birth_place": {"city": "Москва", "region": "", "country": "Россия"},
                },
            },
            "S5": {"questionnaire": {"status": "in_progress", "answered_count": 7, "total_questions": 12}},
            "S6": {},
            "S7": {"report_job_status": "pending"},
        }

        for screen_id, state in scenarios.items():
            with self.subTest(screen_id=screen_id):
                content = manager.render_screen(screen_id, user_id=1, state=state)
                self.assertGreaterEqual(len(content.messages), 1)
                for message in content.messages:
                    self.assertLessEqual(len(message), manager._telegram_message_limit)
                    self.assertEqual(len(manager._split_message(message)), 1)


if __name__ == "__main__":
    unittest.main()
