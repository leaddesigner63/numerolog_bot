import unittest

from app.bot.screens import build_report_wait_message


class ReportWaitMessageTests(unittest.TestCase):
    def test_includes_progress_bar_when_total_is_known(self) -> None:
        text = build_report_wait_message(
            remaining_seconds=6,
            frame="🔄",
            total_seconds=12,
        )

        self.assertIn("Прогресс:", text)
        self.assertIn("50%", text)
        self.assertIn("[██████░░░░░░]", text)

    def test_hides_progress_bar_without_total(self) -> None:
        text = build_report_wait_message(remaining_seconds=3, frame="⌛")

        self.assertNotIn("Прогресс:", text)
        self.assertIn("Осталось: 3 сек.", text)


if __name__ == "__main__":
    unittest.main()
