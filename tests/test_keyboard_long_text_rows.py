import unittest

from aiogram.types import InlineKeyboardButton

from app.bot.keyboards import enforce_long_button_rows


class KeyboardLongTextRowsTests(unittest.TestCase):
    def test_splits_long_text_rows_into_two_buttons(self) -> None:
        rows = [
            [
                InlineKeyboardButton(text="Очень длинная кнопка 1", callback_data="a"),
                InlineKeyboardButton(text="Очень длинная кнопка 2", callback_data="b"),
                InlineKeyboardButton(text="Очень длинная кнопка 3", callback_data="c"),
            ]
        ]

        normalized = enforce_long_button_rows(rows)

        self.assertEqual([len(row) for row in normalized], [2, 1])

    def test_keeps_short_text_rows_without_split(self) -> None:
        rows = [
            [
                InlineKeyboardButton(text="1", callback_data="a"),
                InlineKeyboardButton(text="2", callback_data="b"),
                InlineKeyboardButton(text="3", callback_data="c"),
            ]
        ]

        normalized = enforce_long_button_rows(rows)

        self.assertEqual([len(row) for row in normalized], [3])

    def test_splits_rows_when_button_text_longer_than_eight_chars(self) -> None:
        rows = [
            [
                InlineKeyboardButton(text="123456789", callback_data="a"),
                InlineKeyboardButton(text="123456789", callback_data="b"),
                InlineKeyboardButton(text="123456789", callback_data="c"),
            ]
        ]

        normalized = enforce_long_button_rows(rows)

        self.assertEqual([len(row) for row in normalized], [2, 1])


if __name__ == "__main__":
    unittest.main()
