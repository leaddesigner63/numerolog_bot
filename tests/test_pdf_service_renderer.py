from pathlib import Path
import unittest
from unittest import mock

from app.core.config import settings
from app.core.pdf_service import PdfService, PdfThemeRenderer
from app.core.pdf_themes import resolve_pdf_theme


class _CanvasSpy:
    def __init__(self) -> None:
        self.draw_calls: list[tuple[float, float, str]] = []

    def saveState(self) -> None:  # noqa: N802
        return None

    def restoreState(self) -> None:  # noqa: N802
        return None

    def setFillColor(self, *_args, **_kwargs) -> None:  # noqa: N802
        return None

    def setFont(self, *_args, **_kwargs) -> None:  # noqa: N802
        return None

    def drawString(self, x: float, y: float, text: str) -> None:  # noqa: N802
        self.draw_calls.append((x, y, text))


class PdfServiceRendererTests(unittest.TestCase):
    def test_generate_pdf_falls_back_to_legacy_on_renderer_error(self) -> None:
        service = PdfService()

        with mock.patch(
            "app.core.pdf_service.PdfThemeRenderer.render",
            side_effect=RuntimeError("boom"),
        ):
            pdf = service.generate_pdf("hello", tariff="UNKNOWN", meta={"id": "1"})

        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_generate_pdf_with_partial_font_family_fallback(self) -> None:
        with mock.patch.object(
            settings,
            "pdf_font_regular_path",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ), mock.patch.object(settings, "pdf_font_bold_path", "/no/such/font-bold.ttf"), mock.patch.object(
            settings,
            "pdf_font_accent_path",
            "/no/such/font-accent.ttf",
        ), mock.patch("app.core.pdf_service._FONT_FAMILY", None):
            pdf = PdfService().generate_pdf("Заголовок 123\nОсновной текст", tariff="T1", meta={"id": "2"})

        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_generate_pdf_cyrillic_smoke(self) -> None:
        regular = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        bold = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        accent = Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf")
        if not (regular.exists() and bold.exists() and accent.exists()):
            self.skipTest("System DejaVu fonts are not available in this environment")

        with mock.patch.object(settings, "pdf_font_regular_path", str(regular)), mock.patch.object(
            settings,
            "pdf_font_bold_path",
            str(bold),
        ), mock.patch.object(settings, "pdf_font_accent_path", str(accent)), mock.patch(
            "app.core.pdf_service._FONT_FAMILY",
            None,
        ):
            pdf = PdfService().generate_pdf(
                "Привет, это кириллический smoke-тест 2026",
                tariff="T2",
                meta={"id": "77"},
            )

        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn(b"/ToUnicode", pdf)

    def test_split_line_by_width_preserves_all_characters(self) -> None:
        renderer = PdfThemeRenderer()
        source = "СВЕРХДЛИННОЕСЛОВО" * 30

        lines = renderer._split_line_by_width(
            source,
            font="Helvetica",
            size=11,
            width=120,
        )

        self.assertGreater(len(lines), 1)
        self.assertEqual("".join(lines), source)


    def test_split_text_into_visual_lines_strips_control_and_zero_width_chars(self) -> None:
        renderer = PdfThemeRenderer()
        source = "когда город за\rтихал, а\u200b в его руках"

        lines = renderer._split_text_into_visual_lines(
            source,
            font="Helvetica",
            size=11,
            width=500,
        )

        self.assertEqual(lines, ["когда город за", "тихал, а в его руках"])

    def test_split_text_into_visual_lines_preserves_empty_lines(self) -> None:
        renderer = PdfThemeRenderer()
        source = "Первая строка\n\nТретья строка"

        lines = renderer._split_text_into_visual_lines(
            source,
            font="Helvetica",
            size=11,
            width=500,
        )

        self.assertEqual(lines, ["Первая строка", "", "Третья строка"])

    def test_draw_header_wraps_long_title_without_dropping_text(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        canvas = _CanvasSpy()
        long_title = (
            "Минимум на тяжёлый день — чётко определить одну главную задачу дня "
            "и сделать перерыв для полной перезагрузки"
        )

        body_start_y = renderer._draw_header(
            canvas,
            theme,
            {"title": "Helvetica", "subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"},
            meta={"id": "42"},
            tariff="T1",
            page_width=240,
            page_height=842,
            report_document=mock.Mock(title=long_title, subtitle="Тариф: T1"),
        )

        self.assertGreaterEqual(len(canvas.draw_calls), 3)
        rendered_title_lines = [text for _, _, text in canvas.draw_calls[:-1]]
        self.assertEqual("".join(rendered_title_lines).replace(" ", ""), long_title.replace(" ", ""))
        self.assertLess(body_start_y, 760)


if __name__ == "__main__":
    unittest.main()
