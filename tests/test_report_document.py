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

    def test_build_strips_markdown_noise_from_title_and_bullets(self) -> None:
        builder = ReportDocumentBuilder()
        doc = builder.build(
            """## 🔍 Проверка данных\n\nКлючевые выводы:\n* **Как включить:** сначала уточни цель\n* __Второй пункт__\n""",
            tariff="T1",
            meta={"id": "13"},
        )
        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertEqual(doc.title, "Проверка данных")
        self.assertTrue(doc.key_findings)
        self.assertIn("Как включить: сначала уточни цель", doc.key_findings[0])


if __name__ == "__main__":
    unittest.main()
