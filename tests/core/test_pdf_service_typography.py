from unittest import mock

from app.core.config import settings
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
## Почему это важно: так ты удерживаешь вектор и не теряешь темп.
"""


SECTION_WITH_NON_WHITELIST_COLON_FIXTURE = """Персональный аналитический отчёт

Ресурс и фокус:
Сильная сторона: устойчивость в период высокой нагрузки.
"""


SECTION_WITH_MIXED_SUBSECTIONS_FIXTURE = """Персональный аналитический отчёт

Ресурс и фокус:
Почему это важно: это помогает сохранить темп и ясность действий.
Сильная сторона: удерживаешь спокойствие даже при внешнем давлении.
"""


def _collect_text_draw_calls(fixture: str, tariff: str) -> tuple[list[dict], object]:
    builder = ReportDocumentBuilder()
    doc = builder.build(fixture, tariff=tariff, meta={"id": f"fixture-{tariff.lower()}"})
    assert doc is not None

    renderer = PdfThemeRenderer()
    theme = resolve_pdf_theme(tariff)
    text_calls: list[dict] = []

    def fake_draw_text_block(_pdf, **kwargs):
        call = dict(kwargs)
        call["resolved_text_color_rgb"] = kwargs.get("text_color_rgb") or kwargs["theme"].typography.body_color_rgb
        text_calls.append(call)
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

    return text_calls, theme


def test_draw_body_uses_section_title_and_body_typography_colors_for_heading_case() -> None:
    text_calls, theme = _collect_text_draw_calls(SECTION_WITH_PARAGRAPH_FIXTURE, "T1")

    title_call = next(call for call in text_calls if call["text"] == "Ресурс и фокус")
    paragraph_call = next(
        call
        for call in text_calls
        if call["text"] == "Сохраняй один приоритет на день и возвращайся к нему после пауз."
    )

    assert title_call["text_color_rgb"] == theme.typography.section_title_color_rgb
    assert paragraph_call["resolved_text_color_rgb"] == theme.typography.body_color_rgb


def test_draw_body_treats_wrapped_short_lines_as_body_paragraph() -> None:
    text_calls, theme = _collect_text_draw_calls(WRAPPED_PARAGRAPH_FIXTURE, "T1")

    paragraph_call = next(
        call
        for call in text_calls
        if call["text"] == "Иногда ритм сбивается, и это нормально когда нагрузка растёт."
    )

    assert paragraph_call["resolved_text_color_rgb"] == theme.typography.body_color_rgb
    assert paragraph_call["font"] == "Helvetica"
    assert paragraph_call["size"] == theme.typography.body_size


def test_draw_body_uses_subsection_typography_color_for_short_label_paragraph() -> None:
    text_calls, theme = _collect_text_draw_calls(SECTION_WITH_SUBSECTION_FIXTURE, "T1")

    subsection_call = next(call for call in text_calls if call["text"] == "Почему это важно")
    paragraph_call = next(
        call
        for call in text_calls
        if call["text"] == "так ты удерживаешь вектор и не теряешь темп."
    )

    assert subsection_call["text_color_rgb"] == theme.typography.subsection_title_color_rgb
    assert paragraph_call["resolved_text_color_rgb"] == theme.typography.body_color_rgb


def test_draw_body_keeps_non_whitelist_colon_paragraph_in_body_color_for_t3() -> None:
    with mock.patch.object(settings, "pdf_subsection_fallback_heuristic_enabled", True):
        text_calls, theme = _collect_text_draw_calls(SECTION_WITH_NON_WHITELIST_COLON_FIXTURE, "T3")

    non_whitelist_colon_call = next(
        call
        for call in text_calls
        if call["text"] == "Сильная сторона: устойчивость в период высокой нагрузки."
    )

    assert non_whitelist_colon_call["resolved_text_color_rgb"] == theme.typography.body_color_rgb
    assert non_whitelist_colon_call["resolved_text_color_rgb"] != theme.typography.subsection_title_color_rgb


def test_draw_body_applies_subsection_color_only_for_allowed_labels_in_t3() -> None:
    with mock.patch.object(settings, "pdf_subsection_fallback_heuristic_enabled", True):
        text_calls, theme = _collect_text_draw_calls(SECTION_WITH_MIXED_SUBSECTIONS_FIXTURE, "T3")

    allowed_subsection_call = next(call for call in text_calls if call["text"] == "Почему это важно")
    allowed_subsection_body_call = next(
        call
        for call in text_calls
        if call["text"] == "это помогает сохранить темп и ясность действий."
    )
    non_whitelist_colon_call = next(
        call
        for call in text_calls
        if call["text"] == "Сильная сторона: удерживаешь спокойствие даже при внешнем давлении."
    )

    assert allowed_subsection_call["resolved_text_color_rgb"] == theme.typography.subsection_title_color_rgb
    assert allowed_subsection_body_call["resolved_text_color_rgb"] == theme.typography.body_color_rgb
    assert non_whitelist_colon_call["resolved_text_color_rgb"] == theme.typography.body_color_rgb
