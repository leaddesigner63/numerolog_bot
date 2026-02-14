from unittest import mock

from app.core.pdf_service import PdfThemeRenderer
from app.core.pdf_themes import resolve_pdf_theme
from app.core.report_document import ReportDocumentBuilder


SECTION_WITH_PARAGRAPH_FIXTURE = """Персональный аналитический отчёт

Ресурс и фокус:
Сохраняй один приоритет на день и возвращайся к нему после пауз.
"""


WRAPPED_PARAGRAPH_FIXTURE = """Персональный аналитический отчёт

Иногда ритм сбивается,
и это нормально
когда нагрузка растёт.
"""


SECTION_WITH_SUBSECTION_FIXTURE = """Персональный аналитический отчёт

Ресурс и фокус:
Почему это важно: так ты удерживаешь вектор и не теряешь темп.
"""


def test_draw_body_uses_section_title_and_body_typography_colors_for_heading_case() -> None:
    builder = ReportDocumentBuilder()
    doc = builder.build(SECTION_WITH_PARAGRAPH_FIXTURE, tariff="T1", meta={"id": "fixture-3"})
    assert doc is not None

    renderer = PdfThemeRenderer()
    theme = resolve_pdf_theme("T1")

    text_calls: list[dict] = []

    def fake_draw_text_block(_pdf, **kwargs):
        text_calls.append(kwargs)
        return kwargs["y"]

    with mock.patch.object(renderer, "_draw_content_surface"), mock.patch.object(
        renderer,
        "_draw_text_block",
        side_effect=fake_draw_text_block,
    ), mock.patch.object(renderer, "_draw_bullet_item", side_effect=lambda _pdf, **kwargs: kwargs["y"]):
        renderer._draw_body(
            mock.Mock(),
            theme,
            {"subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"},
            report_text="",
            page_width=595,
            page_height=842,
            asset_bundle=mock.Mock(),
            body_start_y=700,
            report_document=doc,
        )

    title_call = next(call for call in text_calls if call["text"] == "Ресурс и фокус")
    paragraph_call = next(
        call
        for call in text_calls
        if call["text"] == "Сохраняй один приоритет на день и возвращайся к нему после пауз."
    )

    assert title_call["text_color_rgb"] == theme.typography.section_title_color_rgb
    assert paragraph_call.get("text_color_rgb") is None


def test_draw_body_treats_wrapped_short_lines_as_body_paragraph() -> None:
    builder = ReportDocumentBuilder()
    doc = builder.build(WRAPPED_PARAGRAPH_FIXTURE, tariff="T1", meta={"id": "fixture-4"})
    assert doc is not None

    renderer = PdfThemeRenderer()
    theme = resolve_pdf_theme("T1")

    text_calls: list[dict] = []

    def fake_draw_text_block(_pdf, **kwargs):
        text_calls.append(kwargs)
        return kwargs["y"]

    with mock.patch.object(renderer, "_draw_content_surface"), mock.patch.object(
        renderer,
        "_draw_text_block",
        side_effect=fake_draw_text_block,
    ), mock.patch.object(renderer, "_draw_bullet_item", side_effect=lambda _pdf, **kwargs: kwargs["y"]):
        renderer._draw_body(
            mock.Mock(),
            theme,
            {"subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"},
            report_text="",
            page_width=595,
            page_height=842,
            asset_bundle=mock.Mock(),
            body_start_y=700,
            report_document=doc,
        )

    paragraph_call = next(
        call
        for call in text_calls
        if call["text"] == "Иногда ритм сбивается, и это нормально когда нагрузка растёт."
    )

    assert paragraph_call.get("text_color_rgb") is None
    assert paragraph_call["font"] == "Helvetica"
    assert paragraph_call["size"] == theme.typography.body_size


def test_draw_body_uses_subsection_typography_color_for_short_label_paragraph() -> None:
    builder = ReportDocumentBuilder()
    doc = builder.build(SECTION_WITH_SUBSECTION_FIXTURE, tariff="T1", meta={"id": "fixture-5"})
    assert doc is not None

    renderer = PdfThemeRenderer()
    theme = resolve_pdf_theme("T1")

    text_calls: list[dict] = []

    def fake_draw_text_block(_pdf, **kwargs):
        text_calls.append(kwargs)
        return kwargs["y"]

    with mock.patch.object(renderer, "_draw_content_surface"), mock.patch.object(
        renderer,
        "_draw_text_block",
        side_effect=fake_draw_text_block,
    ), mock.patch.object(renderer, "_draw_bullet_item", side_effect=lambda _pdf, **kwargs: kwargs["y"]):
        renderer._draw_body(
            mock.Mock(),
            theme,
            {"subtitle": "Helvetica-Bold", "body": "Helvetica", "numeric": "Helvetica"},
            report_text="",
            page_width=595,
            page_height=842,
            asset_bundle=mock.Mock(),
            body_start_y=700,
            report_document=doc,
        )

    subsection_call = next(call for call in text_calls if call["text"] == "Почему это важно")
    paragraph_call = next(
        call
        for call in text_calls
        if call["text"] == "так ты удерживаешь вектор и не теряешь темп."
    )

    assert subsection_call["text_color_rgb"] == theme.typography.subsection_title_color_rgb
    assert paragraph_call.get("text_color_rgb") is None
