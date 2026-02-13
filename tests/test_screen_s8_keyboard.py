import unittest

from app.bot import screens


class ScreenS8KeyboardTests(unittest.TestCase):
    def test_s8_has_no_inline_keyboard_while_waiting_text_input(self) -> None:
        content = screens.screen_s8({})
        self.assertIsNone(content.keyboard)


if __name__ == "__main__":
    unittest.main()
