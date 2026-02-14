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

    def test_build_uses_tariff_display_title_without_report_id(self) -> None:
        builder = ReportDocumentBuilder()
        doc = builder.build(
            """Персональный аналитический отчёт

- Первый вывод
""",
            tariff="T2",
            meta={"id": "55"},
        )

        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertEqual(doc.subtitle, "Где твои деньги?")
        self.assertNotIn("Report #", doc.subtitle)
        self.assertNotIn("Тариф: T2", doc.subtitle)

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

    def test_build_strips_malformed_html_fragments_from_paragraphs(self) -> None:
        builder = ReportDocumentBuilder()
        doc = builder.build(
            """Минимум на тяжёлый день:
</i> Сделай одну маленькую вещь, которая принесёт тебе радость.
<i> Запиши три вещи, за которые ты благодарен.
</i> Удали из головы одну ненужную заботу.
""",
            tariff="T1",
            meta={"id": "42"},
        )

        self.assertIsNotNone(doc)
        assert doc is not None
        paragraphs = doc.sections[0].paragraphs
        self.assertEqual(
            paragraphs,
            [
                "Сделай одну маленькую вещь, которая принесёт тебе радость.",
                "Запиши три вещи, за которые ты благодарен.",
                "Удали из головы одну ненужную заботу.",
            ],
        )

    def test_keeps_bullets_inside_named_section_after_paragraphs(self) -> None:
        builder = ReportDocumentBuilder()
        doc = builder.build(
            """Персональный аналитический отчёт

Ритм и восстановление:
Твой внутренний ритм может требовать паузы.

Минимум на тяжёлый день:
- 15 минут полного молчания, чтобы услышать себя.
- Короткая прогулка на свежем воздухе, чтобы обновить мысли.
- Отказ от одной необязательной задачи, чтобы освободить ресурс.
""",
            tariff="T1",
            meta={"id": "21"},
        )

        self.assertIsNotNone(doc)
        assert doc is not None
        minimum_section = next((section for section in doc.sections if section.title == "Минимум на тяжёлый день"), None)
        self.assertIsNotNone(minimum_section)
        assert minimum_section is not None
        self.assertEqual(
            minimum_section.bullets,
            [
                "15 минут полного молчания, чтобы услышать себя.",
                "Короткая прогулка на свежем воздухе, чтобы обновить мысли.",
                "Отказ от одной необязательной задачи, чтобы освободить ресурс.",
            ],
        )


if __name__ == "__main__":
    unittest.main()
