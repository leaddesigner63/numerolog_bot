import unittest

from app.bot.handlers.profile import GENDER_CALLBACK_TO_VALUE, _gender_keyboard


class ProfileGenderButtonsTests(unittest.TestCase):
    def test_gender_keyboard_has_two_expected_buttons(self) -> None:
        keyboard = _gender_keyboard()

        self.assertEqual(len(keyboard.inline_keyboard), 1)
        callback_data = [button.callback_data for button in keyboard.inline_keyboard[0]]
        self.assertEqual(callback_data, ["profile:gender:female", "profile:gender:male"])

    def test_gender_callback_mapping_values(self) -> None:
        self.assertEqual(GENDER_CALLBACK_TO_VALUE["profile:gender:female"], "Женский")
        self.assertEqual(GENDER_CALLBACK_TO_VALUE["profile:gender:male"], "Мужской")


if __name__ == "__main__":
    unittest.main()
