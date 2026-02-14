import unittest

from app.core.pdf_service import PdfThemeRenderer
from app.core.report_document import SUBSECTION_CONTRACT_PREFIX, ReportDocumentBuilder

from app.core.report_service import ReportService


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
        self.assertFalse(any(section.title == "Титульный лист T3" for section in doc.sections))

    def test_returns_none_for_empty_text(self) -> None:
        builder = ReportDocumentBuilder()
        self.assertIsNone(builder.build("\n\n", tariff="T1"))

    def test_build_uses_tariff_label_prefix_without_report_id(self) -> None:
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
        self.assertEqual(doc.subtitle, "Тариф: Где твои деньги?")
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

    def test_marks_explicit_subsection_lines_with_contract_prefix(self) -> None:
        builder = ReportDocumentBuilder()
        doc = builder.build(
            """Персональный аналитический отчёт

Раздел:
## Фокус: держи темп
Обычный абзац.
""",
            tariff="T1",
            meta={"id": "88"},
        )

        self.assertIsNotNone(doc)
        assert doc is not None
        section = next((item for item in doc.sections if item.title == "Раздел"), None)
        self.assertIsNotNone(section)
        assert section is not None
        self.assertEqual(section.paragraphs[0], f"{SUBSECTION_CONTRACT_PREFIX}Фокус: держи темп")
        self.assertEqual(section.paragraphs[1], "Обычный абзац.")

    def test_build_preserves_timeline_lines_with_mixed_dashes(self) -> None:
        builder = ReportDocumentBuilder()
        source = """Персональный аналитический отчёт

План действий:
1 месяц (по неделям):
Неделя 1: навести порядок в режиме.

1 год (помесячно):
1-3: стабилизировать рабочий режим.
4–6: усилить концентрацию.
7-9: расширить круг задач.
10–12: закрепить устойчивый результат.

Следующий шаг,
который поможет удерживать темп.
"""

        doc = builder.build(source, tariff="T1", meta={"id": "timeline-integration"})

        self.assertIsNotNone(doc)
        assert doc is not None
        week_section = next((section for section in doc.sections if section.title == "1 месяц (по неделям)"), None)
        self.assertIsNotNone(week_section)
        assert week_section is not None
        self.assertEqual(week_section.paragraphs, ["Неделя 1: навести порядок в режиме."])

        month_section = next((section for section in doc.sections if section.title == "1 год (помесячно)"), None)
        self.assertIsNotNone(month_section)
        assert month_section is not None
        self.assertEqual(
            month_section.paragraphs,
            [
                "1-3: стабилизировать рабочий режим.",
                "4–6: усилить концентрацию.",
                "7-9: расширить круг задач.",
                "10–12: закрепить устойчивый результат.",
                "Следующий шаг, который поможет удерживать темп.",
            ],
        )

    def test_t3_fallback_plan_subsections_are_converted_to_contract_prefix(self) -> None:
        builder = ReportDocumentBuilder()
        fallback_text = ReportService()._build_fallback_report({"selected_tariff": "T3"})

        doc = builder.build(fallback_text, tariff="T3", meta={"id": "777"})

        self.assertIsNotNone(doc)
        assert doc is not None
        plan_section = next((section for section in doc.sections if section.title == "План действий"), None)
        self.assertIsNotNone(plan_section)
        assert plan_section is not None
        self.assertEqual(
            plan_section.paragraphs,
            [
                f"{SUBSECTION_CONTRACT_PREFIX}1 месяц (по неделям)",
                f"{SUBSECTION_CONTRACT_PREFIX}1 год (по месяцам)",
                f"{SUBSECTION_CONTRACT_PREFIX}Энергия и отношения",
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


    def test_build_uses_neutral_default_section_title(self) -> None:
        builder = ReportDocumentBuilder()
        doc = builder.build(
            """Персональный аналитический отчёт

Это первый абзац без именованных разделов.
- И буллет в том же блоке.
""",
            tariff="T1",
            meta={"id": "301"},
        )

        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertTrue(doc.sections)
        self.assertEqual(doc.sections[0].title, "")
        self.assertNotEqual(doc.sections[0].title, "Основные разделы")

    def test_filters_diagnostic_sections_and_bullets_without_breaking_render(self) -> None:
        builder = ReportDocumentBuilder()
        source = """Персональный аналитический отчёт

- Главный акцент: держать фокус на сильных сторонах.
- Не распознано поле даты рождения.

Проверка данных:
- Не полностью заполнено поле времени рождения.
- Ошибка парсинга входного JSON.

Сильные стороны:
- Ты быстро адаптируешься к изменениям и сохраняешь устойчивость.
"""

        doc = builder.build(source, tariff="T1", meta={"id": "100"})

        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertTrue(all(section.title != "Проверка данных" for section in doc.sections))
        self.assertTrue(all("не распознано" not in point.lower() for point in doc.key_findings))
        self.assertTrue(all("ошибка парсинга" not in bullet.lower() for section in doc.sections for bullet in section.bullets))

        renderer = PdfThemeRenderer()
        payload = renderer.render(source, tariff="T1", meta={"id": "100"}, report_document=doc)
        self.assertTrue(payload.startswith(b"%PDF"))

    def test_filters_standalone_service_line_from_key_findings(self) -> None:
        builder = ReportDocumentBuilder()
        source = """Твой путь к себе!

- Проверка данных
- Главный вывод для пользователя.
"""

        doc = builder.build(source, tariff="T3", meta={"id": "301"})

        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertTrue(all("проверка данных" not in point.lower() for point in doc.key_findings))
        self.assertIn("Главный вывод для пользователя.", doc.key_findings)

    def test_removes_pdf_promo_phrases_from_findings_and_sections(self) -> None:
        builder = ReportDocumentBuilder()
        source = """Персональный аналитический отчёт

- Бесплатный превью-отчёт доступен раз в месяц.
- Это превью твоих сильных сторон.

Подробности:
Это превью и бесплатный превью-отчёт о текущем состоянии.
- Доступен раз в месяц.
- Конкретный рабочий вывод без промо-фраз.
"""

        doc = builder.build(source, tariff="T1", meta={"id": "201"})

        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertTrue(all("бесплатный превью-отчёт" not in point.lower() for point in doc.key_findings))
        self.assertTrue(all("доступен раз в месяц" not in point.lower() for point in doc.key_findings))
        self.assertTrue(all("это превью" not in point.lower() for point in doc.key_findings))
        self.assertTrue(all("доступен раз в месяц" not in paragraph.lower() for section in doc.sections for paragraph in section.paragraphs))
        self.assertTrue(all("это превью" not in paragraph.lower() for section in doc.sections for paragraph in section.paragraphs))
        self.assertTrue(all("бесплатный превью-отчёт" not in bullet.lower() for section in doc.sections for bullet in section.bullets))
        self.assertTrue(any("конкретный рабочий вывод" in bullet.lower() for section in doc.sections for bullet in section.bullets))
        self.assertTrue(all(section.bullets or section.paragraphs or section.accent_blocks for section in doc.sections))

    def test_short_standalone_line_becomes_section_title(self) -> None:
        builder = ReportDocumentBuilder()
        source = """Персональный аналитический отчёт

Вектор роста
Сейчас полезно сохранить фокус на одной ключевой цели.
"""

        doc = builder.build(source, tariff="T1", meta={"id": "202"})

        self.assertIsNotNone(doc)
        assert doc is not None
        section = next((item for item in doc.sections if item.title == "Вектор роста"), None)
        self.assertIsNotNone(section)
        assert section is not None
        self.assertEqual(section.paragraphs, ["Сейчас полезно сохранить фокус на одной ключевой цели."])

    def test_removes_t3_subtitle_artifact_line_from_pdf_content(self) -> None:
        builder = ReportDocumentBuilder()
        source = """Твой путь к себе!

«Твой путь к себе!» — персональный маршрут

Лёгкое вступление:
Это содержательная часть отчёта, которая должна остаться.
"""

        doc = builder.build(source, tariff="T3", meta={"id": "303"})

        self.assertIsNotNone(doc)
        assert doc is not None
        all_paragraphs = [paragraph for section in doc.sections for paragraph in section.paragraphs]
        self.assertFalse(any("персональный маршрут" in paragraph.lower() for paragraph in all_paragraphs))
        self.assertTrue(any("содержательная часть отчёта" in paragraph.lower() for paragraph in all_paragraphs))

    def test_question_and_exclamation_lines_prefer_paragraphs(self) -> None:
        builder = ReportDocumentBuilder()
        source = """Персональный аналитический отчёт

Где твой ресурс?
Опирайся на рутину сна и короткие прогулки.

С чего начать!
Выбери один шаг и повторяй его неделю.
"""

        doc = builder.build(source, tariff="T1", meta={"id": "203"})

        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertFalse(any(section.title == "Где твой ресурс?" for section in doc.sections))
        self.assertFalse(any(section.title == "С чего начать!" for section in doc.sections))
        all_paragraphs = [paragraph for section in doc.sections for paragraph in section.paragraphs]
        self.assertIn("Где твой ресурс?", all_paragraphs)
        self.assertIn("С чего начать!", all_paragraphs)

    def test_long_line_with_connectors_is_not_promoted_to_title(self) -> None:
        builder = ReportDocumentBuilder()
        source = """Персональный аналитический отчёт

Почему это важно и как это помогает, когда фокус теряется
Выбери одно действие и повторяй его ежедневно.
"""

        doc = builder.build(source, tariff="T1", meta={"id": "206"})

        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertFalse(any(section.title == "Почему это важно и как это помогает, когда фокус теряется" for section in doc.sections))
        all_paragraphs = [paragraph for section in doc.sections for paragraph in section.paragraphs]
        self.assertTrue(any(paragraph.startswith("Почему это важно и как это помогает, когда фокус теряется") for paragraph in all_paragraphs))

    def test_short_standalone_subheadings_without_colon_become_section_titles(self) -> None:
        builder = ReportDocumentBuilder()
        source = """Персональный аналитический отчёт

Вектор роста
Сузь фокус до одной цели и отслеживай прогресс ежедневно.

Точка опоры
Верни стабильный ритм сна и отдыха.
"""

        doc = builder.build(source, tariff="T1", meta={"id": "205"})

        self.assertIsNotNone(doc)
        assert doc is not None
        growth_section = next((section for section in doc.sections if section.title == "Вектор роста"), None)
        support_section = next((section for section in doc.sections if section.title == "Точка опоры"), None)
        self.assertIsNotNone(growth_section)
        self.assertIsNotNone(support_section)
        assert growth_section is not None
        assert support_section is not None

        all_paragraphs = [paragraph for section in doc.sections for paragraph in section.paragraphs]
        self.assertNotIn("Вектор роста", all_paragraphs)
        self.assertNotIn("Точка опоры", all_paragraphs)
        self.assertEqual(growth_section.paragraphs, ["Сузь фокус до одной цели и отслеживай прогресс ежедневно."])
        self.assertEqual(support_section.paragraphs, ["Верни стабильный ритм сна и отдыха."])

    def test_merges_wrapped_lines_into_single_paragraph_before_parsing(self) -> None:
        builder = ReportDocumentBuilder()
        source = """Персональный аналитический отчёт

В этом блоке первая строка
продолжает мысль без разрыва
и должна остаться в одном абзаце.
"""

        doc = builder.build(source, tariff="T1", meta={"id": "206"})

        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertEqual(
            doc.sections[0].paragraphs,
            ["В этом блоке первая строка продолжает мысль без разрыва и должна остаться в одном абзаце."],
        )

    def test_keeps_explicit_titles_bullets_and_separators_when_merging_lines(self) -> None:
        builder = ReportDocumentBuilder()
        source = """Персональный аналитический отчёт

Фокус:
Первая строка абзаца
вторая строка абзаца
---
- Отдельный пункт
"""

        doc = builder.build(source, tariff="T1", meta={"id": "207"})

        self.assertIsNotNone(doc)
        assert doc is not None
        section = next((item for item in doc.sections if item.title == "Фокус"), None)
        self.assertIsNotNone(section)
        assert section is not None
        self.assertEqual(section.paragraphs, ["Первая строка абзаца вторая строка абзаца"])
        self.assertIn("Отдельный пункт", section.bullets)

    def test_does_not_treat_long_or_warning_sentences_as_titles(self) -> None:
        builder = ReportDocumentBuilder()
        source = """Персональный аналитический отчёт

Внимание!
Это предложение слишком длинное, чтобы считаться заголовком даже с восклицанием!
Короткая фраза, но с запятой.
"""

        doc = builder.build(source, tariff="T1", meta={"id": "204"})

        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertTrue(doc.sections)
        self.assertEqual(doc.sections[0].title, "")
        self.assertIn("Внимание!", doc.sections[0].paragraphs)
        self.assertIn(
            "Это предложение слишком длинное, чтобы считаться заголовком даже с восклицанием!",
            doc.sections[0].paragraphs,
        )
        self.assertIn("Короткая фраза, но с запятой.", doc.sections[0].paragraphs)



if __name__ == "__main__":
    unittest.main()
