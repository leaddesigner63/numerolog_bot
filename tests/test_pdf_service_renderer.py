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




class _CoverCanvasSpy:
    def __init__(self) -> None:
        self.show_page_calls = 0

    def saveState(self) -> None:  # noqa: N802
        return None

    def restoreState(self) -> None:  # noqa: N802
        return None

    def setFillColor(self, *_args, **_kwargs) -> None:  # noqa: N802
        return None

    def setFont(self, *_args, **_kwargs) -> None:  # noqa: N802
        return None

    def drawCentredString(self, *_args, **_kwargs) -> None:  # noqa: N802
        return None

    def showPage(self) -> None:  # noqa: N802
        self.show_page_calls += 1

    def save(self) -> None:
        return None


class _DecorCanvasSpy:
    def __init__(self) -> None:
        self.drawn_strings: list[str] = []

    def saveState(self) -> None:  # noqa: N802
        return None

    def restoreState(self) -> None:  # noqa: N802
        return None

    def setFillColor(self, *_args, **_kwargs) -> None:  # noqa: N802
        return None

    def circle(self, *_args, **_kwargs) -> None:
        return None

    def drawString(self, _x: float, _y: float, text: str) -> None:  # noqa: N802
        self.drawn_strings.append(text)


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




    def test_render_adds_cover_page_when_cover_asset_exists(self) -> None:
        renderer = PdfThemeRenderer()
        cover_canvas = _CoverCanvasSpy()

        with self.subTest('with cover'):
            with mock.patch('app.core.pdf_service._register_font', return_value={'title': 'Helvetica-Bold'}), mock.patch(
                'app.core.pdf_service.resolve_pdf_theme',
                return_value=mock.Mock(palette=[None, None, 'accent']),
            ), mock.patch('app.core.pdf_service.canvas.Canvas', return_value=cover_canvas), mock.patch.object(
                renderer,
                '_draw_background',
                return_value=None,
            ), mock.patch.object(renderer, '_draw_decorative_layers', return_value=None), mock.patch.object(
                renderer,
                '_draw_header',
                return_value=700,
            ), mock.patch.object(renderer, '_draw_body', return_value=None), mock.patch.object(
                renderer,
                '_try_draw_image_layer',
                return_value=True,
            ):
                with unittest.mock.patch('app.core.pdf_service.resolve_pdf_asset_bundle') as bundle_mock:
                    from tempfile import TemporaryDirectory

                    with TemporaryDirectory() as tmp:
                        tmp_path = Path(tmp)
                        bg_main = tmp_path / 't1_bg_main.webp'
                        bg_cover = tmp_path / 't1_bg_cover.webp'
                        icon_main = tmp_path / 't1_icon_main.png'
                        bg_main.touch()
                        bg_cover.touch()
                        icon_main.touch()
                        bundle_mock.return_value = mock.Mock(
                            background_main=bg_main,
                            background_fallback=bg_main,
                            overlay_main=icon_main,
                            overlay_fallback=icon_main,
                            icon_main=icon_main,
                            icon_fallback=icon_main,
                        )
                        renderer.render('text', tariff='T1', meta={'id': '9'})

        self.assertEqual(cover_canvas.show_page_calls, 1)

    def test_draw_decorative_layers_does_not_draw_stars_or_digits(self) -> None:
        renderer = PdfThemeRenderer()
        canvas = _DecorCanvasSpy()

        with mock.patch.object(renderer, '_try_draw_image_layer', return_value=False):
            renderer._draw_decorative_layers(
                canvas,
                resolve_pdf_theme('T1'),
                page_width=595,
                page_height=842,
                randomizer=mock.Mock(uniform=lambda a, _b: a),
                asset_bundle=mock.Mock(
                    overlay_main=Path('missing_overlay.png'),
                    overlay_fallback=Path('missing_overlay_fallback.png'),
                    icon_main=Path('missing_icon.png'),
                    icon_fallback=Path('missing_icon_fallback.png'),
                ),
            )

        self.assertEqual(canvas.drawn_strings, [])


if __name__ == "__main__":
    unittest.main()
