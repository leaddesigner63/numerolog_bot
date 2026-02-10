import unittest
from unittest.mock import Mock, patch

from app.bot.handlers import screens
from app.db.models import Report


class ReportDeleteResilienceTests(unittest.TestCase):
    def test_delete_report_with_assets_keeps_flow_on_pdf_delete_error(self) -> None:
        session = Mock()
        report = Report(id=123)
        report.pdf_storage_key = "broken-key"

        with patch.object(
            screens.pdf_service,
            "delete_pdf",
            side_effect=RuntimeError("storage unavailable"),
        ):
            deleted = screens._delete_report_with_assets(session, report)

        self.assertTrue(deleted)
        session.delete.assert_called_once_with(report)

    def test_delete_report_with_assets_returns_false_when_db_delete_fails(self) -> None:
        session = Mock()
        session.delete.side_effect = RuntimeError("db error")
        report = Report(id=7)
        report.pdf_storage_key = None

        with patch.object(screens.pdf_service, "delete_pdf"):
            deleted = screens._delete_report_with_assets(session, report)

        self.assertFalse(deleted)


if __name__ == "__main__":
    unittest.main()
