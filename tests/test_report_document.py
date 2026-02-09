import unittest

from app.core.report_document import ReportDocumentBuilder


class ReportDocumentBuilderTests(unittest.TestCase):
    def test_build_structured_document_for_t3(self) -> None:
        builder = ReportDocumentBuilder()
        doc = builder.build(
            """Персональный аналитический отчёт\n\nРезюме:\n• Первый вывод\n• Второй вывод\n\nСильные стороны:\n- Аналитичность\n- Системность\n\nСервис не является консультацией...""",
            tariff="T3",
            meta={"id": "9"},
        )
        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertEqual(doc.tariff, "T3")
        self.assertEqual(doc.decoration_depth, 3)
        self.assertTrue(doc.key_findings)
        self.assertTrue(any(section.title == "Титульный лист T3" for section in doc.sections))

    def test_returns_none_for_empty_text(self) -> None:
        builder = ReportDocumentBuilder()
        self.assertIsNone(builder.build("\n\n", tariff="T1"))


if __name__ == "__main__":
    unittest.main()
