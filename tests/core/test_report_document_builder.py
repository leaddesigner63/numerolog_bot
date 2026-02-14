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
