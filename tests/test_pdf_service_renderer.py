from pathlib import Path
import tempfile
import unittest
from unittest import mock

from app.core.config import settings
from app.core.pdf_service import PdfService, PdfThemeRenderer
from app.core.pdf_themes import resolve_pdf_theme


class _CanvasSpy:
    def __init__(self) -> None:
        self.draw_calls: list[tuple[float, float, str]] = []
        self.page_breaks = 0

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

    def showPage(self) -> None:  # noqa: N802
        self.page_breaks += 1


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


    def test_draw_decorative_layers_keeps_only_graphics_without_text_symbols(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        asset_bundle = mock.Mock(
            overlay_main=Path("/tmp/overlay.png"),
            overlay_fallback=Path("/tmp/overlay-fallback.png"),
            icon_main=Path("/tmp/icon.png"),
            icon_fallback=Path("/tmp/icon-fallback.png"),
        )

        draw_calls: list[str] = []
        circles: list[tuple[float, float, float]] = []

        canvas = mock.Mock()
        canvas.drawString.side_effect = lambda _x, _y, text: draw_calls.append(text)
        canvas.circle.side_effect = lambda x, y, r, **_kwargs: circles.append((x, y, r))

        with mock.patch.object(renderer, "_try_draw_image_layer", return_value=True) as draw_layer:
            renderer._draw_decorative_layers(
                canvas,
                theme,
                page_width=595,
                page_height=842,
                randomizer=mock.Mock(
                    uniform=mock.Mock(return_value=42.0),
                    randint=mock.Mock(return_value=7),
                ),
                asset_bundle=asset_bundle,
            )

        self.assertEqual(draw_layer.call_count, 2)
        self.assertEqual(len(circles), theme.splash_count)
        self.assertEqual(draw_calls, [])

    def test_draw_cover_page_returns_false_when_cover_background_is_missing(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        pdf = mock.Mock()
        font_map = {"title": "Helvetica", "subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"}

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            background_main = root / "t1_bg_main.webp"
            icon_main = root / "t1_icon_main.png"
            icon_main.write_bytes(b"icon")
            asset_bundle = mock.Mock(
                background_main=background_main,
                icon_main=icon_main,
            )

            result = renderer._draw_cover_page(
                pdf,
                theme,
                font_map,
                meta={},
                tariff="T1",
                page_width=595,
                page_height=842,
                asset_bundle=asset_bundle,
            )

        self.assertFalse(result)
        pdf.showPage.assert_not_called()

    def test_draw_cover_page_uses_cover_icon_and_creates_new_page(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        pdf = mock.Mock()
        font_map = {"title": "Helvetica", "subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"}

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            background_main = root / "t1_bg_main.webp"
            cover_background = root / "t1_bg_cover.webp"
            icon_main = root / "t1_icon_main.png"
            cover_icon = root / "t1_icon_cover.png"
            background_main.write_bytes(b"bg-main")
            cover_background.write_bytes(b"bg-cover")
            icon_main.write_bytes(b"icon-main")
            cover_icon.write_bytes(b"icon-cover")
            asset_bundle = mock.Mock(
                background_main=background_main,
                icon_main=icon_main,
            )

            with mock.patch.object(renderer, "_try_draw_image_layer", return_value=True) as draw_layer:
                result = renderer._draw_cover_page(
                    pdf,
                    theme,
                    font_map,
                    meta={"id": "123"},
                    tariff="T1",
                    page_width=595,
                    page_height=842,
                    asset_bundle=asset_bundle,
                )

        self.assertTrue(result)
        self.assertEqual(draw_layer.call_count, 2)
        self.assertEqual(draw_layer.call_args_list[0].kwargs["primary"], cover_background)
        self.assertEqual(draw_layer.call_args_list[1].kwargs["primary"], cover_icon)
        self.assertEqual(draw_layer.call_args_list[1].kwargs["x"], (595 - 110) / 2)
        self.assertEqual(draw_layer.call_args_list[1].kwargs["width"], 110)
        self.assertEqual(draw_layer.call_args_list[1].kwargs["height"], 110)
        pdf.showPage.assert_called_once()

    def test_draw_cover_page_uses_tariff_title_without_subtitle_or_report_id(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        pdf = _CanvasSpy()
        font_map = {"title": "Helvetica", "subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"}

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            background_main = root / "t1_bg_main.webp"
            cover_background = root / "t1_bg_cover.webp"
            icon_main = root / "t1_icon_main.png"
            background_main.write_bytes(b"bg-main")
            cover_background.write_bytes(b"bg-cover")
            icon_main.write_bytes(b"icon-main")
            asset_bundle = mock.Mock(
                background_main=background_main,
                icon_main=icon_main,
            )

            with mock.patch.object(renderer, "_try_draw_image_layer", return_value=True):
                result = renderer._draw_cover_page(
                    pdf,
                    theme,
                    font_map,
                    meta={"id": "777"},
                    tariff="T1",
                    page_width=595,
                    page_height=842,
                    asset_bundle=asset_bundle,
                    report_document=mock.Mock(title="Старый тайтл", subtitle="Старый сабтайтл"),
                )

        self.assertTrue(result)
        rendered_text = " ".join(text for _, _, text in pdf.draw_calls)
        self.assertIn("В чём твоя сила?", rendered_text)
        self.assertNotIn("Report #777", rendered_text)
        self.assertNotIn("Старый сабтайтл", rendered_text)
        self.assertEqual(pdf.page_breaks, 1)


    def test_draw_cover_page_uses_fallback_title_for_unknown_tariff(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        pdf = _CanvasSpy()
        font_map = {"title": "Helvetica", "subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"}

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            background_main = root / "t1_bg_main.webp"
            cover_background = root / "t1_bg_cover.webp"
            icon_main = root / "t1_icon_main.png"
            background_main.write_bytes(b"bg-main")
            cover_background.write_bytes(b"bg-cover")
            icon_main.write_bytes(b"icon-main")
            asset_bundle = mock.Mock(
                background_main=background_main,
                icon_main=icon_main,
            )

            with mock.patch.object(renderer, "_try_draw_image_layer", return_value=True):
                result = renderer._draw_cover_page(
                    pdf,
                    theme,
                    font_map,
                    meta={},
                    tariff="CUSTOM",
                    page_width=595,
                    page_height=842,
                    asset_bundle=asset_bundle,
                )

        self.assertTrue(result)
        rendered_text = " ".join(text for _, _, text in pdf.draw_calls)
        self.assertIn("Персональный отчёт", rendered_text)
        self.assertEqual(pdf.page_breaks, 1)


if __name__ == "__main__":
    unittest.main()
