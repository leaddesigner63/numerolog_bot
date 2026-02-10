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


if __name__ == "__main__":
    unittest.main()
