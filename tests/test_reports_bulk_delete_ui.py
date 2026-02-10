import unittest

from app.bot.screens import screen_s12, screen_s14


class ReportsBulkDeleteUiTests(unittest.TestCase):
    def test_s12_shows_bulk_delete_button_when_reports_exist(self) -> None:
        content = screen_s12({"reports": [{"id": 1}], "reports_total": 1})

        buttons = [
            button
            for row in content.keyboard.inline_keyboard
            for button in row
        ]
        callback_data = [button.callback_data for button in buttons]

        self.assertIn("report:delete_all", callback_data)

    def test_s12_hides_bulk_delete_button_when_reports_empty(self) -> None:
        content = screen_s12({"reports": [], "reports_total": 0})

        buttons = [
            button
            for row in content.keyboard.inline_keyboard
            for button in row
        ]
        callback_data = [button.callback_data for button in buttons]

        self.assertNotIn("report:delete_all", callback_data)

    def test_s14_uses_bulk_delete_confirmation_callbacks(self) -> None:
        content = screen_s14({"report_delete_scope": "all"})

        first_row = content.keyboard.inline_keyboard[0]
        self.assertEqual(first_row[0].callback_data, "report:delete:confirm_all")
        self.assertEqual(first_row[1].callback_data, "screen:S12")
        self.assertIn("Удалить все отчёты", content.messages[0])


if __name__ == "__main__":
    unittest.main()
