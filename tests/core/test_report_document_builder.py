import pytest

from app.core.report_document import ReportDocumentBuilder


WRAPPED_PARAGRAPH_FIXTURE = """Персональный аналитический отчёт

Иногда ритм сбивается,
и это нормально
когда нагрузка растёт.
"""


SECTION_WITH_PARAGRAPH_FIXTURE = """Персональный аналитический отчёт

Ресурс и фокус:
Сохраняй один приоритет на день и возвращайся к нему после пауз.
"""


TIMELINE_PLAN_LINES_FIXTURE = [
    "План действий:",
    "1 месяц (по неделям):",
    "Неделя 1: замедлиться и убрать перегруз.",
    "Неделя 2: закрепить комфортный ритм.",
    "1 год (помесячно):",
    "1–3: стабилизировать рабочий режим.",
    "4–6: усилить концентрацию.",
    "7–9: расширить круг задач.",
    "10–12: закрепить устойчивый результат.",
]

TIMELINE_RANGE_HYPHEN_LINES_FIXTURE = [
    "1 год (помесячно):",
    "1-3: стабилизировать рабочий режим.",
    "4-6: усилить концентрацию.",
    "7-9: расширить круг задач.",
    "10-12: закрепить устойчивый результат.",
]


@pytest.mark.parametrize(
    ("source", "expected_paragraph"),
    [
        (
            WRAPPED_PARAGRAPH_FIXTURE,
            "Иногда ритм сбивается, и это нормально когда нагрузка растёт.",
        ),
        (
            """Персональный аналитический отчёт

Фокус можно вернуть,
если дробить путь
на короткие шаги.
""",
            "Фокус можно вернуть, если дробить путь на короткие шаги.",
        ),
        (
            """Персональный аналитический отчёт

Остановись на минуту,
выдохни,
и продолжай в своём темпе.
""",
            "Остановись на минуту, выдохни, и продолжай в своём темпе.",
        ),
    ],
)
def test_build_keeps_wrapped_short_lines_as_body_paragraph(source: str, expected_paragraph: str) -> None:
    builder = ReportDocumentBuilder()

    doc = builder.build(source, tariff="T1", meta={"id": "fixture-1"})

    assert doc is not None
    assert doc.sections
    first_section = doc.sections[0]
    assert first_section.title == ""
    assert first_section.bullets == []
    assert first_section.paragraphs == [
        expected_paragraph,
    ]


def test_build_splits_explicit_section_title_and_paragraph() -> None:
    builder = ReportDocumentBuilder()

    doc = builder.build(SECTION_WITH_PARAGRAPH_FIXTURE, tariff="T1", meta={"id": "fixture-2"})

    assert doc is not None
    assert doc.sections
    target_section = doc.sections[0]
    assert target_section.title == "Ресурс и фокус"
    assert target_section.paragraphs == [
        "Сохраняй один приоритет на день и возвращайся к нему после пауз.",
    ]
    assert target_section.bullets == []


def test_merge_multiline_paragraphs_keeps_timeline_plan_lines_separate() -> None:
    builder = ReportDocumentBuilder()
    merged = builder._merge_multiline_paragraphs(TIMELINE_PLAN_LINES_FIXTURE)

    assert merged == TIMELINE_PLAN_LINES_FIXTURE


def test_merge_multiline_paragraphs_still_merges_regular_narrative() -> None:
    builder = ReportDocumentBuilder()
    lines = [
        "Иногда ритм сбивается,",
        "и это нормально",
        "когда нагрузка растёт.",
    ]

    merged = builder._merge_multiline_paragraphs(lines)

    assert merged == ["Иногда ритм сбивается, и это нормально когда нагрузка растёт."]



def test_merge_multiline_paragraphs_keeps_timeline_ranges_with_hyphen_separate() -> None:
    builder = ReportDocumentBuilder()
    merged = builder._merge_multiline_paragraphs(TIMELINE_RANGE_HYPHEN_LINES_FIXTURE)

    assert merged == TIMELINE_RANGE_HYPHEN_LINES_FIXTURE


def test_merge_multiline_paragraphs_preserves_timeline_line_after_blank_line() -> None:
    builder = ReportDocumentBuilder()
    lines = [
        "1 месяц (по неделям):",
        "",
        "Неделя 1: снизить темп и перераспределить нагрузку.",
        "Иногда полезно делать маленькие шаги,",
        "чтобы возвращать контроль.",
    ]

    merged = builder._merge_multiline_paragraphs(lines)

    assert merged == [
        "1 месяц (по неделям):",
        "",
        "Неделя 1: снизить темп и перераспределить нагрузку.",
        "Иногда полезно делать маленькие шаги, чтобы возвращать контроль.",
    ]
