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

TIMELINE_RANGE_EM_DASH_LINES_FIXTURE = [
    "1 год (помесячно):",
    "1 — 3: стабилизировать рабочий режим.",
    "4 — 6: усилить концентрацию.",
    "7 — 9: расширить круг задач.",
    "10 — 12: закрепить устойчивый результат.",
]

FULL_T3_PLAN_WITH_BLANK_LINES_FIXTURE = """Персональный аналитический отчёт

План действий:
1 месяц (по неделям):
Неделя 1: стабилизировать ритм и сон.

Неделя 2: закрепить режим восстановления.
Неделя 3: расширить регулярные практики.

Неделя 4: зафиксировать устойчивый график.
1 год (помесячно):
1–3: адаптировать рабочую нагрузку.

4–6: усилить концентрацию и фокус.
7–9: масштабировать полезные привычки.

10–12: закрепить итоговый результат.
"""


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


def test_merge_multiline_paragraphs_keeps_timeline_ranges_with_em_dash_separate() -> None:
    builder = ReportDocumentBuilder()
    merged = builder._merge_multiline_paragraphs(TIMELINE_RANGE_EM_DASH_LINES_FIXTURE)

    assert merged == TIMELINE_RANGE_EM_DASH_LINES_FIXTURE


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


def test_build_keeps_full_t3_timeline_periods_as_separate_paragraphs() -> None:
    builder = ReportDocumentBuilder()

    doc = builder.build(FULL_T3_PLAN_WITH_BLANK_LINES_FIXTURE, tariff="T3", meta={"id": "fixture-t3"})

    assert doc is not None
    assert len(doc.sections) >= 2
    assert doc.sections[0].title == "1 месяц (по неделям)"
    assert doc.sections[0].paragraphs == [
        "Неделя 1: стабилизировать ритм и сон.",
        "Неделя 2: закрепить режим восстановления.",
        "Неделя 3: расширить регулярные практики.",
        "Неделя 4: зафиксировать устойчивый график.",
    ]
    assert doc.sections[1].title == "1 год (помесячно)"
    assert doc.sections[1].paragraphs == [
        "1–3: адаптировать рабочую нагрузку.",
        "4–6: усилить концентрацию и фокус.",
        "7–9: масштабировать полезные привычки.",
        "10–12: закрепить итоговый результат.",
    ]
    combined_timeline_paragraphs = doc.sections[0].paragraphs + doc.sections[1].paragraphs
    assert all("Неделя 1:" not in paragraph or "Неделя 2:" not in paragraph for paragraph in combined_timeline_paragraphs)
    assert all("1–3:" not in paragraph or "4–6:" not in paragraph for paragraph in combined_timeline_paragraphs)


def test_merge_multiline_paragraphs_preserves_blank_lines_between_t3_periods() -> None:
    builder = ReportDocumentBuilder()

    merged = builder._merge_multiline_paragraphs(FULL_T3_PLAN_WITH_BLANK_LINES_FIXTURE.splitlines()[3:])

    assert merged == [
        "1 месяц (по неделям):",
        "Неделя 1: стабилизировать ритм и сон.",
        "",
        "Неделя 2: закрепить режим восстановления.",
        "Неделя 3: расширить регулярные практики.",
        "",
        "Неделя 4: зафиксировать устойчивый график.",
        "1 год (помесячно):",
        "1–3: адаптировать рабочую нагрузку.",
        "",
        "4–6: усилить концентрацию и фокус.",
        "7–9: масштабировать полезные привычки.",
        "",
        "10–12: закрепить итоговый результат.",
    ]


def test_merge_multiline_paragraphs_preserves_multiple_blank_lines_between_t3_periods() -> None:
    builder = ReportDocumentBuilder()
    lines = [
        "1 месяц (по неделям):",
        "Неделя 1: стабилизировать ритм и сон.",
        "",
        "",
        "Неделя 2: закрепить режим восстановления.",
        "1 год (помесячно):",
        "1 — 3: адаптировать рабочую нагрузку.",
        "",
        "",
        "4 — 6: усилить концентрацию и фокус.",
    ]

    merged = builder._merge_multiline_paragraphs(lines)

    assert merged == lines


def test_build_combines_week_headers_with_weekly_detail_bullets() -> None:
    source = """Персональный аналитический отчёт

План действий:
Неделя 2
Взгляд на свои ресурсы
Неделя 3
Разговоры по душам
- фокус недели: личность/опора/ритм/самоценность/привычки.
- старт недели: сделай утреннюю прогулку.
- критерий успеха недели: больше спокойствия.
- фокус недели: отношения/границы/коммуникация.
- старт недели: запланируй тёплый разговор.
- критерий успеха недели: ясность в контакте.
"""
    builder = ReportDocumentBuilder()

    doc = builder.build(source, tariff="T3", meta={"id": "fixture-weekly-combine"})

    assert doc is not None
    plan_section = next((section for section in doc.sections if section.title == "План действий"), None)
    assert plan_section is not None
    assert plan_section.paragraphs == [
        "Неделя 2 — Взгляд на свои ресурсы: фокус недели: личность/опора/ритм/самоценность/привычки.; "
        "старт недели: сделай утреннюю прогулку.; критерий успеха недели: больше спокойствия.",
        "Неделя 3 — Разговоры по душам: фокус недели: отношения/границы/коммуникация.; "
        "старт недели: запланируй тёплый разговор.; критерий успеха недели: ясность в контакте.",
    ]
    assert plan_section.bullets == []


def test_build_keeps_original_structure_when_weekly_bullet_chunks_do_not_match_weeks() -> None:
    source = """Персональный аналитический отчёт

План действий:
Неделя 2
Взгляд на свои ресурсы
Неделя 3
Разговоры по душам
- фокус недели: личность/опора/ритм.
- старт недели: сделай утреннюю прогулку.
"""
    builder = ReportDocumentBuilder()

    doc = builder.build(source, tariff="T3", meta={"id": "fixture-weekly-no-combine"})

    assert doc is not None
    plan_section = next((section for section in doc.sections if section.title == "План действий"), None)
    assert plan_section is not None
    assert plan_section.paragraphs == ["Неделя 2", "Взгляд на свои ресурсы", "Неделя 3", "Разговоры по душам"]
    assert plan_section.bullets == [
        "фокус недели: личность/опора/ритм.",
        "старт недели: сделай утреннюю прогулку.",
    ]
