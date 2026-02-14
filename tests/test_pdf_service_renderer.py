from pathlib import Path
import tempfile
import unittest
from unittest import mock

from app.core.config import settings
from app.core.pdf_service import PdfService, PdfThemeRenderer
from app.core.pdf_themes import resolve_pdf_theme
from app.core.report_document import ReportAccentBlock, ReportDocument, ReportSection


class _CanvasTextSpy:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y
        self.text = ""
        self.font_name = ""
        self.font_size = 0
        self.char_space = 0.0

    def setFont(self, font_name: str, font_size: int, *_args, **_kwargs) -> None:  # noqa: N802
        self.font_name = font_name
        self.font_size = font_size

    def setCharSpace(self, char_space: float, *_args, **_kwargs) -> None:  # noqa: N802
        self.char_space = char_space

    def textLine(self, text: str) -> None:  # noqa: N802
        self.text = text


class _CanvasSpy:
    def __init__(self) -> None:
        self.draw_calls: list[tuple[float, float, str]] = []
        self.draw_calls_with_page: list[tuple[int, float, float, str]] = []
        self.page_breaks = 0
        self.current_page = 1
        self.text_draw_calls: list[tuple[int, float, float, str, str, int, tuple[float, ...]]] = []
        self.current_fill_color: tuple[float, ...] = ()

    def saveState(self) -> None:  # noqa: N802
        return None

    def restoreState(self) -> None:  # noqa: N802
        return None

    def setFillColor(self, *_args, **_kwargs) -> None:  # noqa: N802
        return None

    def setFillColorRGB(self, *args, **kwargs) -> None:  # noqa: N802
        alpha = kwargs.get("alpha")
        if alpha is None:
            self.current_fill_color = tuple(args)
            return None
        self.current_fill_color = (*args, alpha)
        return None

    def setFillAlpha(self, *_args, **_kwargs) -> None:  # noqa: N802
        return None

    def setStrokeColor(self, *_args, **_kwargs) -> None:  # noqa: N802
        return None

    def setLineWidth(self, *_args, **_kwargs) -> None:  # noqa: N802
        return None

    def roundRect(self, *_args, **_kwargs) -> None:  # noqa: N802
        return None

    def setFont(self, *_args, **_kwargs) -> None:  # noqa: N802
        return None

    def beginText(self, x: float, y: float) -> _CanvasTextSpy:  # noqa: N802
        return _CanvasTextSpy(x, y)

    def drawText(self, text_object: _CanvasTextSpy) -> None:  # noqa: N802
        self.text_draw_calls.append(
            (
                self.current_page,
                text_object.x,
                text_object.y,
                text_object.text,
                text_object.font_name,
                text_object.font_size,
                self.current_fill_color,
            )
        )

    def drawString(self, x: float, y: float, text: str) -> None:  # noqa: N802
        self.draw_calls.append((x, y, text))
        self.draw_calls_with_page.append((self.current_page, x, y, text))

    def showPage(self) -> None:  # noqa: N802
        self.page_breaks += 1
        self.current_page += 1


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
        self.assertEqual("".join(lines).replace("-", ""), source)



    def test_split_line_by_width_uses_soft_hyphen_priority_for_cyrillic(self) -> None:
        renderer = PdfThemeRenderer()
        source = "сверх\u00adдлинноеслово"

        lines = renderer._split_line_by_width(
            source,
            font="Helvetica",
            size=11,
            width=35,
        )

        self.assertGreater(len(lines), 1)
        self.assertTrue(lines[0].endswith("-"))
        self.assertNotIn("\u00ad", "".join(lines))
        restored = "".join(lines).replace("-", "")
        self.assertEqual(restored, source.replace("\u00ad", ""))

    def test_split_line_by_width_hyphenates_mixed_token_without_short_tail(self) -> None:
        renderer = PdfThemeRenderer()
        source = "слово123слово"

        lines = renderer._split_line_by_width(
            source,
            font="Helvetica",
            size=11,
            width=32,
        )

        self.assertGreater(len(lines), 1)
        for line in lines[:-1]:
            self.assertTrue(line.endswith("-"))
        self.assertGreaterEqual(len(lines[-1]), 3)
        restored = "".join(lines).replace("-", "")
        self.assertEqual(restored, source)

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

    def test_draw_header_draws_subtitle_when_report_document_passed(self) -> None:
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

        self.assertEqual(len(canvas.draw_calls), 1)
        self.assertEqual(canvas.draw_calls[0][2], "Тариф: T1")
        self.assertGreater(body_start_y, 740)


    def test_draw_header_uses_tariff_display_title_without_report_id_suffix(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        canvas = _CanvasSpy()

        renderer._draw_header(
            canvas,
            theme,
            {"title": "Helvetica", "subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"},
            meta={"id": "42"},
            tariff="T2",
            page_width=240,
            page_height=842,
            report_document=None,
        )

        rendered_text = " ".join(text for _, _, text in canvas.draw_calls)
        normalized_rendered_text = " ".join(rendered_text.split())
        self.assertIn("Где твои деньги?", normalized_rendered_text)
        self.assertNotIn("Report #42", rendered_text)
        self.assertNotIn("[T2]", rendered_text)



    def test_draw_body_skips_empty_sections_and_empty_key_findings_block(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        canvas = _CanvasSpy()
        report_document = ReportDocument(
            title="Отчёт",
            subtitle="Тариф: T1",
            key_findings=[],
            sections=[
                ReportSection(title="Пустой раздел"),
                ReportSection(title="", paragraphs=["Контент без служебного заголовка."]),
            ],
            disclaimer="Дисклеймер",
        )

        with mock.patch.object(renderer, "_draw_content_surface", return_value=None), mock.patch.object(
            renderer,
            "_draw_background",
            return_value=None,
        ), mock.patch.object(renderer, "_draw_decorative_layers", return_value=None):
            renderer._draw_body(
                canvas,
                theme,
                {"title": "Helvetica-Bold", "subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"},
                report_text="",
                page_width=300,
                page_height=842,
                asset_bundle=mock.Mock(),
                body_start_y=700,
                report_document=report_document,
            )

        rendered_text = [call[3] for call in canvas.text_draw_calls]
        rendered_combined = " ".join(rendered_text)
        self.assertNotIn("Ключевые выводы", rendered_text)
        self.assertNotIn("Пустой раздел", rendered_text)
        self.assertIn("Контент без служебного", rendered_combined)
        self.assertIn("заголовка.", rendered_combined)

    def test_draw_body_moves_section_and_accent_titles_with_first_content_line(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        canvas = _CanvasSpy()

        report_document = ReportDocument(
            title="Отчёт",
            subtitle="Тариф: T1",
            key_findings=["Короткий вывод"],
            sections=[
                ReportSection(
                    title="Раздел переноса",
                    paragraphs=["Первый абзац раздела, который должен идти сразу за заголовком."],
                    accent_blocks=[
                        ReportAccentBlock(
                            title="Важный акцент",
                            points=["Первый пункт акцента следует на той же странице."],
                        )
                    ],
                )
            ],
            disclaimer="Дисклеймер",
        )

        with mock.patch.object(renderer, "_draw_background", return_value=None), mock.patch.object(
            renderer,
            "_draw_decorative_layers",
            return_value=None,
        ):
            renderer._draw_body(
                canvas,
                theme,
                {"title": "Helvetica-Bold", "subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"},
                report_text="",
                page_width=220,
                page_height=160,
                asset_bundle=mock.Mock(),
                body_start_y=108,
                report_document=report_document,
            )

        title_page = next(page for page, _x, _y, text, *_rest in canvas.text_draw_calls if text.startswith("Раздел"))
        paragraph_page = next(
            page
            for page, _x, _y, text, *_rest in canvas.text_draw_calls
            if text.startswith("Первый абзац")
        )
        accent_title_page = next(
            page
            for page, _x, _y, text, *_rest in canvas.text_draw_calls
            if text.startswith("Акцент: Важный")
        )
        accent_point_page = next(
            page
            for page, _x, _y, text in canvas.draw_calls_with_page
            if text.startswith("Первый пункт")
        )

        self.assertEqual(title_page, paragraph_page)
        self.assertEqual(accent_title_page, accent_point_page)


    def test_draw_body_applies_distinct_section_title_style(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        canvas = _CanvasSpy()
        report_document = ReportDocument(
            title="Отчёт",
            subtitle="Тариф: T1",
            key_findings=["Короткий вывод"],
            sections=[
                ReportSection(
                    title="Раздел со стилем",
                    paragraphs=["Обычный абзац тела"],
                )
            ],
            disclaimer="Дисклеймер",
        )

        with mock.patch.object(renderer, "_draw_content_surface", return_value=None), mock.patch.object(
            renderer,
            "_draw_background",
            return_value=None,
        ), mock.patch.object(renderer, "_draw_decorative_layers", return_value=None):
            renderer._draw_body(
                canvas,
                theme,
                {"title": "Helvetica-Bold", "subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"},
                report_text="",
                page_width=300,
                page_height=842,
                asset_bundle=mock.Mock(),
                body_start_y=700,
                report_document=report_document,
            )

        section_title_draw = next(call for call in canvas.text_draw_calls if call[3].startswith("Раздел"))
        body_draw = next(call for call in canvas.text_draw_calls if call[3].startswith("Обычный абзац"))

        self.assertNotEqual(section_title_draw[4], body_draw[4])
        self.assertNotEqual(section_title_draw[5], body_draw[5])
        self.assertNotEqual(section_title_draw[6], body_draw[6])

    def test_draw_body_renders_subsection_title_and_body_separately(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        canvas = _CanvasSpy()
        report_document = ReportDocument(
            title="Отчёт",
            subtitle="Тариф: T1",
            key_findings=[],
            sections=[
                ReportSection(
                    title="Раздел",
                    paragraphs=["Подзаголовок: Абзац после двоеточия"],
                )
            ],
            disclaimer="",
        )

        with mock.patch.object(renderer, "_draw_content_surface", return_value=None), mock.patch.object(
            renderer,
            "_draw_background",
            return_value=None,
        ), mock.patch.object(renderer, "_draw_decorative_layers", return_value=None):
            renderer._draw_body(
                canvas,
                theme,
                {"title": "Helvetica-Bold", "subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"},
                report_text="",
                page_width=300,
                page_height=842,
                asset_bundle=mock.Mock(),
                body_start_y=700,
                report_document=report_document,
            )

        subsection_draw = next(call for call in canvas.text_draw_calls if call[3] == "Подзаголовок")
        body_draw = next(call for call in canvas.text_draw_calls if call[3].startswith("Абзац после"))

        self.assertEqual(subsection_draw[4], "Helvetica-Bold")
        self.assertEqual(subsection_draw[5], theme.typography.subsection_title_size)
        self.assertEqual(subsection_draw[6], (*theme.typography.subsection_title_color_rgb, 1.0))
        self.assertEqual(body_draw[4], "Helvetica")
        self.assertEqual(body_draw[5], theme.typography.body_size)

    def test_render_builds_pdf_with_subsection_typography_level(self) -> None:
        renderer = PdfThemeRenderer()
        source = """Персональный аналитический отчёт

Вектор роста:
Собери один измеримый шаг на ближайшие 7 дней.

Следующий фокус:
Сохраняй ритм и фиксируй результат в конце дня.
"""

        payload = renderer.render(source, tariff="T2", meta={"id": "501"})

        self.assertTrue(payload.startswith(b"%PDF"))

    def test_draw_body_handles_multiple_consecutive_subsection_titles_and_blank_lines(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        canvas = _CanvasSpy()
        report_document = ReportDocument(
            title="Отчёт",
            subtitle="Тариф: T1",
            key_findings=[],
            sections=[
                ReportSection(
                    title="Раздел",
                    paragraphs=[
                        "Фокус: ",
                        "Приоритет: Действие на неделю",
                        "",
                        "Итог: Следующий шаг без провалов",
                    ],
                )
            ],
            disclaimer="",
        )

        with mock.patch.object(renderer, "_draw_content_surface", return_value=None), mock.patch.object(
            renderer,
            "_draw_background",
            return_value=None,
        ), mock.patch.object(renderer, "_draw_decorative_layers", return_value=None):
            renderer._draw_body(
                canvas,
                theme,
                {"title": "Helvetica-Bold", "subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"},
                report_text="",
                page_width=300,
                page_height=842,
                asset_bundle=mock.Mock(),
                body_start_y=700,
                report_document=report_document,
            )

        rendered_text = [call[3] for call in canvas.text_draw_calls]
        rendered_combined = " ".join(part for part in rendered_text if part)
        self.assertIn("Фокус", rendered_text)
        self.assertIn("Приоритет", rendered_text)
        self.assertIn("Итог", rendered_text)
        self.assertIn("Действие на неделю", rendered_combined)
        self.assertIn("Следующий шаг без", rendered_combined)
        self.assertIn("провалов", rendered_combined)

    def test_extract_subsection_title_keeps_raw_user_format(self) -> None:
        renderer = PdfThemeRenderer()

        title, body = renderer._extract_subsection_title("A:   текст в любом формате ###")
        self.assertEqual(title, "A")
        self.assertEqual(body, "текст в любом формате ###")

        title_no_sep, body_no_sep = renderer._extract_subsection_title("без двоеточия")
        self.assertEqual(title_no_sep, "")
        self.assertEqual(body_no_sep, "без двоеточия")


    def test_draw_body_uses_disclaimer_typography_overrides(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        canvas = _CanvasSpy()
        report_document = ReportDocument(
            title="Отчёт",
            subtitle="Тариф: T1",
            key_findings=["Вывод"],
            sections=[],
            disclaimer="Дисклеймер для проверки отдельной типографики.",
        )

        with mock.patch.object(renderer, "_draw_content_surface", return_value=None), mock.patch.object(
            renderer,
            "_draw_text_block",
            wraps=renderer._draw_text_block,
        ) as draw_text_block_spy:
            renderer._draw_body(
                canvas,
                theme,
                {"title": "Helvetica-Bold", "subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"},
                report_text="",
                page_width=300,
                page_height=842,
                asset_bundle=mock.Mock(),
                body_start_y=700,
                report_document=report_document,
            )

        disclaimer_call = next(
            call
            for call in draw_text_block_spy.call_args_list
            if call.kwargs.get("text") == report_document.disclaimer
        )

        self.assertEqual(disclaimer_call.kwargs["size"], max(theme.typography.disclaimer_size, 8))
        self.assertEqual(
            disclaimer_call.kwargs["line_height_ratio"],
            theme.typography.disclaimer_line_height_ratio,
        )

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


    def test_draw_content_surface_uses_dark_fill_and_soft_stroke(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        pdf = mock.Mock()

        renderer._draw_content_surface(pdf, theme, page_width=595, page_height=842)

        pdf.setFillColorRGB.assert_called_once_with(0.06, 0.08, 0.11)
        pdf.setFillAlpha.assert_called_once_with(0.82)
        pdf.setStrokeColor.assert_called_once_with(theme.palette[2], alpha=0.16)
        pdf.setLineWidth.assert_called_once_with(1.0)

    def test_draw_raw_text_block_redraws_content_surface_after_page_break(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        pdf = mock.Mock()

        with mock.patch.object(renderer, "_draw_background"), mock.patch.object(renderer, "_draw_decorative_layers"), mock.patch.object(
            renderer,
            "_draw_content_surface",
        ) as draw_content_surface:
            renderer._draw_raw_text_block(
                pdf,
                text="Первая строка",
                y=theme.margin,
                margin=theme.margin,
                width=300,
                font="Helvetica",
                numeric_font="Helvetica",
                size=11,
                page_width=595,
                page_height=842,
                theme=theme,
                asset_bundle=mock.Mock(),
            )

        pdf.showPage.assert_called_once()
        draw_content_surface.assert_called_once_with(pdf, theme, 595, 842)

    def test_draw_text_block_redraws_content_surface_after_page_break(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        pdf = mock.Mock()

        with mock.patch.object(renderer, "_draw_background"), mock.patch.object(renderer, "_draw_decorative_layers"), mock.patch.object(
            renderer,
            "_draw_content_surface",
        ) as draw_content_surface:
            renderer._draw_text_block(
                pdf,
                text="Первая строка",
                y=theme.margin,
                margin=theme.margin,
                width=300,
                font="Helvetica",
                size=11,
                page_width=595,
                page_height=842,
                theme=theme,
                asset_bundle=mock.Mock(),
            )

        pdf.showPage.assert_called_once()
        draw_content_surface.assert_called_once_with(pdf, theme, 595, 842)



    def test_draw_body_uses_theme_spacing_values_for_offsets(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        typography = theme.typography
        pdf = mock.Mock()
        report_document = mock.Mock(
            decoration_depth=0,
            key_findings=["k1"],
            sections=[
                mock.Mock(
                    title="Section 1",
                    paragraphs=["Paragraph 1"],
                    bullets=["Bullet 1"],
                    accent_blocks=[mock.Mock(title="Accent", points=["Point 1"])],
                )
            ],
            disclaimer="Disclaimer",
        )

        text_calls: list[dict[str, float | str]] = []
        bullet_calls: list[dict[str, float | str]] = []

        def fake_draw_text_block(_pdf, **kwargs):
            text_calls.append(kwargs)
            return kwargs["y"]

        def fake_draw_bullet_item(_pdf, **kwargs):
            bullet_calls.append(kwargs)
            return kwargs["y"]

        with mock.patch.object(renderer, "_draw_content_surface"), mock.patch.object(
            renderer,
            "_draw_text_block",
            side_effect=fake_draw_text_block,
        ), mock.patch.object(renderer, "_draw_bullet_item", side_effect=fake_draw_bullet_item):
            renderer._draw_body(
                pdf,
                theme,
                {"subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"},
                report_text="",
                page_width=595,
                page_height=842,
                asset_bundle=mock.Mock(),
                body_start_y=700,
                report_document=report_document,
            )

        self.assertEqual(text_calls[1]["y"], 700 - typography.section_spacing)
        self.assertEqual(text_calls[3]["y"], text_calls[2]["y"] - typography.section_spacing * 2)
        self.assertEqual(text_calls[1]["margin"], theme.margin + typography.paragraph_spacing)
        self.assertEqual(text_calls[1]["width"], 595 - theme.margin * 2 - typography.paragraph_spacing)
        self.assertEqual(bullet_calls[0]["margin"], theme.margin)
        self.assertEqual(bullet_calls[0]["width"], 595 - theme.margin * 2)
        self.assertEqual(bullet_calls[0]["bullet_indent"], typography.bullet_indent)
        self.assertEqual(bullet_calls[1]["bullet_hanging_indent"], typography.bullet_hanging_indent)
        self.assertEqual(bullet_calls[1]["bullet_indent"], typography.bullet_hanging_indent)

    def test_draw_bullet_item_draws_marker_and_wrapped_lines_with_expected_offsets(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        canvas = _CanvasSpy()

        with mock.patch.object(
            renderer,
            "_split_text_into_visual_lines",
            side_effect=[["Первая строка", "Перенос"], ["Перенос"]],
        ):
            renderer._draw_bullet_item(
                canvas,
                marker="•",
                text="Текст пункта",
                y=500,
                margin=theme.margin,
                width=300,
                bullet_indent=theme.typography.bullet_indent,
                bullet_hanging_indent=theme.typography.bullet_hanging_indent,
                font="Helvetica",
                size=theme.typography.body_size,
                page_width=595,
                page_height=842,
                theme=theme,
                asset_bundle=mock.Mock(),
            )

        first_marker_x, _first_marker_y, marker_text = canvas.draw_calls[0]
        first_text_x, _first_text_y, first_text = canvas.draw_calls[1]
        wrapped_text_x, _wrapped_text_y, wrapped_text = canvas.draw_calls[2]

        self.assertEqual(marker_text, "•")
        self.assertEqual(first_text, "Первая строка")
        self.assertEqual(wrapped_text, "Перенос")
        self.assertEqual(first_marker_x, theme.margin)
        self.assertEqual(first_text_x, theme.margin + theme.typography.bullet_indent)
        self.assertEqual(wrapped_text_x, theme.margin + theme.typography.bullet_hanging_indent)

    def test_draw_text_block_uses_theme_paragraph_spacing_for_return_value(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")
        pdf = mock.Mock()
        text_obj = mock.Mock()
        pdf.beginText.return_value = text_obj

        start_y = 600
        result_y = renderer._draw_text_block(
            pdf,
            text="Одна строка",
            y=start_y,
            margin=theme.margin,
            width=300,
            font="Helvetica",
            size=theme.typography.body_size,
            page_width=595,
            page_height=842,
            theme=theme,
            asset_bundle=mock.Mock(),
        )

        line_height = int(theme.typography.body_size * theme.typography.line_height_ratio)
        expected_y = start_y - line_height - theme.typography.paragraph_spacing
        self.assertEqual(result_y, expected_y)


    def test_draw_text_block_uses_theme_letter_spacing(self) -> None:
        renderer = PdfThemeRenderer()
        theme = resolve_pdf_theme("T1")

        body_pdf = mock.Mock()
        body_text_obj = mock.Mock()
        body_pdf.beginText.return_value = body_text_obj
        renderer._draw_text_block(
            body_pdf,
            text="Body",
            y=500,
            margin=theme.margin,
            width=300,
            font="Helvetica",
            size=theme.typography.body_size,
            page_width=595,
            page_height=842,
            theme=theme,
            asset_bundle=mock.Mock(),
        )

        title_pdf = mock.Mock()
        title_text_obj = mock.Mock()
        title_pdf.beginText.return_value = title_text_obj
        renderer._draw_text_block(
            title_pdf,
            text="Title",
            y=500,
            margin=theme.margin,
            width=300,
            font="Helvetica-Bold",
            size=theme.typography.body_size + 1,
            page_width=595,
            page_height=842,
            theme=theme,
            asset_bundle=mock.Mock(),
        )

        body_text_obj.setCharSpace.assert_called_with(theme.typography.letter_spacing_body)
        title_text_obj.setCharSpace.assert_called_with(theme.typography.letter_spacing_title)


if __name__ == "__main__":
    unittest.main()
