from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.bot.handlers import screens as screens_handler
from app.db.models import Tariff


class ReportPdfCanonicalTextTests(TestCase):
    def test_generate_pdf_prefers_stored_canonical_report_text(self) -> None:
        report = SimpleNamespace(
            id=18,
            pdf_storage_key=None,
            report_text="<b>Сырой</b>",
            report_text_canonical="Итоговый",
            tariff=Tariff.T1,
            created_at=datetime(2026, 2, 21, 12, 0, 0),
        )
        session = SimpleNamespace(add=lambda *_args, **_kwargs: None)

        with (
            patch.object(
                screens_handler.report_document_builder,
                "build",
                return_value={"doc": "ok"},
            ) as build_report_document,
            patch.object(
                screens_handler.pdf_service,
                "generate_pdf",
                return_value=b"pdf",
            ) as generate_pdf,
            patch.object(
                screens_handler.pdf_service,
                "store_pdf",
                return_value="stored-key",
            ),
        ):
            pdf_bytes = screens_handler._get_report_pdf_bytes(session, report)

        self.assertEqual(pdf_bytes, b"pdf")
        self.assertEqual(build_report_document.call_args.args[0], "Итоговый")
        self.assertEqual(generate_pdf.call_args.args[0], "Итоговый")

    def test_generate_pdf_uses_canonical_report_text(self) -> None:
        report = SimpleNamespace(
            id=17,
            pdf_storage_key=None,
            report_text="<b>План</b><br>Рост",
            report_text_canonical=None,
            tariff=Tariff.T1,
            created_at=datetime(2026, 2, 21, 12, 0, 0),
        )
        session = SimpleNamespace(add=lambda *_args, **_kwargs: None)

        with (
            patch.object(
                screens_handler.report_document_builder,
                "build",
                return_value={"doc": "ok"},
            ) as build_report_document,
            patch.object(
                screens_handler.pdf_service,
                "generate_pdf",
                return_value=b"pdf",
            ) as generate_pdf,
            patch.object(
                screens_handler.pdf_service,
                "store_pdf",
                return_value="stored-key",
            ),
        ):
            pdf_bytes = screens_handler._get_report_pdf_bytes(session, report)

        self.assertEqual(pdf_bytes, b"pdf")
        build_report_document.assert_called_once()
        generate_pdf.assert_called_once()
        self.assertEqual(build_report_document.call_args.args[0], "План\nРост")
        self.assertEqual(generate_pdf.call_args.args[0], "План\nРост")


if __name__ == "__main__":
    import unittest

    unittest.main()
