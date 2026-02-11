import unittest

from app.bot.screens import _sanitize_report_text, screen_s7, screen_s13


class ReportHtmlSanitizationTests(unittest.TestCase):
    def test_sanitize_report_text_removes_supported_html_tags(self) -> None:
        source = (
            'Текст <i>курсив</i> и <b>жирный</b> с <a href="https://example.com">ссылкой</a> '\
            'и переносом<br>строки'
        )

        cleaned = _sanitize_report_text(source, tariff="T1")

        self.assertEqual(cleaned, "Текст курсив и жирный с ссылкой и переносом\nстроки")

    def test_sanitize_report_text_decodes_entities_and_strips_angle_brackets(self) -> None:
        source = "&lt;div&gt;Текст &amp; детали&lt;/div&gt; хвост < и >"

        cleaned = _sanitize_report_text(source, tariff="T2")

        self.assertEqual(cleaned, "Текст & детали хвост  и ")

    def test_screen_s7_strips_html_like_tags_from_report_body(self) -> None:
        content = screen_s7(
            {
                "report_text": "<i>Пункт</i>\n<i>Ещё пункт</i>",
                "report_job_status": "completed",
                "selected_tariff": "T3",
            }
        )

        self.assertIn("Пункт", content.messages[0])
        self.assertIn("Ещё пункт", content.messages[0])
        self.assertNotIn("<i>", content.messages[0])
        self.assertNotIn("</i>", content.messages[0])

    def test_screen_s13_strips_html_like_tags_from_report_body(self) -> None:
        content = screen_s13(
            {
                "report_text": "<i>Раздел</i>",
                "report_meta": {"id": 1, "tariff": "T1", "created_at": "2026-02-08 10:00"},
            }
        )

        self.assertIn("Раздел", content.messages[0])
        self.assertNotIn("<i>", content.messages[0])

    def test_sanitize_report_text_removes_unknown_html_tags(self) -> None:
        source = "<h3>Заголовок</h3><div>Абзац</div><br><custom-tag attr='x'>Текст</custom-tag>"

        cleaned = _sanitize_report_text(source, tariff="T0")

        self.assertEqual(cleaned, "ЗаголовокАбзац\nТекст")

    def test_sanitize_report_text_logs_quality_incident_when_changed(self) -> None:
        with self.assertLogs("app.bot.screens", level="WARNING") as logs:
            _sanitize_report_text("<b>ok</b>", tariff="T1")

        self.assertTrue(any("report_text_postprocess_quality_incident" in entry for entry in logs.output))


if __name__ == "__main__":
    unittest.main()
