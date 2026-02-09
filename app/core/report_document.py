from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.db.models import Tariff


@dataclass(slots=True)
class ReportAccentBlock:
    title: str
    points: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ReportSection:
    title: str
    bullets: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    accent_blocks: list[ReportAccentBlock] = field(default_factory=list)


@dataclass(slots=True)
class ReportDocument:
    title: str
    subtitle: str
    key_findings: list[str] = field(default_factory=list)
    sections: list[ReportSection] = field(default_factory=list)
    disclaimer: str = ""
    tariff: str = "T1"
    decoration_depth: int = 1


class ReportDocumentBuilder:
    _DEFAULT_TITLE = "Персональный аналитический отчёт"
    _DEFAULT_DISCLAIMER = (
        "Сервис не является консультацией, прогнозом или рекомендацией к действию. "
        "Все выводы носят аналитический и описательный характер. "
        "Ответственность за решения остаётся за пользователем. "
        "Сервис не гарантирует финансовых или иных результатов. Возвратов нет."
    )

    def build(
        self,
        report_text: str,
        *,
        tariff: Tariff | str | None,
        meta: dict[str, Any] | None = None,
    ) -> ReportDocument | None:
        try:
            tariff_value = self._resolve_tariff_value(tariff)
            lines = [line.strip() for line in (report_text or "").splitlines()]
            non_empty = [line for line in lines if line]
            if not non_empty:
                return None

            title = non_empty[0][:140] if len(non_empty[0]) > 6 else self._DEFAULT_TITLE
            report_id = (meta or {}).get("id")
            subtitle = f"Тариф: {tariff_value}"
            if report_id:
                subtitle = f"{subtitle} · Report #{report_id}"

            key_findings: list[str] = []
            sections: list[ReportSection] = []
            current = ReportSection(title="Основные разделы")

            for raw_line in non_empty[1:]:
                if self._is_title(raw_line):
                    if current.paragraphs or current.bullets or current.accent_blocks:
                        sections.append(current)
                    current = ReportSection(title=raw_line.rstrip(":"))
                    continue
                bullet = self._extract_bullet(raw_line)
                if bullet is not None:
                    if len(key_findings) < 6 and not sections:
                        key_findings.append(bullet)
                    else:
                        current.bullets.append(bullet)
                    continue
                if raw_line.lower().startswith("дисклеймер"):
                    continue
                current.paragraphs.append(raw_line)

            if current.paragraphs or current.bullets or current.accent_blocks:
                sections.append(current)

            if not key_findings:
                key_findings = [
                    point
                    for section in sections
                    for point in section.bullets[:2]
                ][:5]

            if tariff_value in {"T2", "T3"}:
                self._append_focus_block(sections)
            if tariff_value == "T3":
                self._append_t3_cover(sections)

            return ReportDocument(
                title=title,
                subtitle=subtitle,
                key_findings=key_findings,
                sections=sections or [ReportSection(title="Отчёт", paragraphs=[report_text])],
                disclaimer=self._extract_disclaimer(report_text),
                tariff=tariff_value,
                decoration_depth=self._decoration_depth(tariff_value),
            )
        except Exception:
            return None

    def _resolve_tariff_value(self, tariff: Tariff | str | None) -> str:
        if isinstance(tariff, Tariff):
            return tariff.value
        raw = str(tariff or "T1")
        return raw if raw in {"T0", "T1", "T2", "T3"} else "T1"

    def _is_title(self, line: str) -> bool:
        line = line.strip()
        return line.endswith(":") or line.startswith("##")

    def _extract_bullet(self, line: str) -> str | None:
        stripped = line.strip()
        markers = ("- ", "• ", "* ")
        for marker in markers:
            if stripped.startswith(marker):
                return stripped[len(marker) :].strip()
        if len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in {")", "."}:
            return stripped[2:].strip()
        return None

    def _extract_disclaimer(self, text: str) -> str:
        lowered = text.lower()
        if "сервис не является" in lowered:
            tail = text[lowered.index("сервис не является") :]
            return " ".join(tail.splitlines())[:500]
        return self._DEFAULT_DISCLAIMER

    def _decoration_depth(self, tariff: str) -> int:
        return {"T0": 0, "T1": 1, "T2": 2, "T3": 3}.get(tariff, 1)

    def _append_focus_block(self, sections: list[ReportSection]) -> None:
        sections.append(
            ReportSection(
                title="Акцент: практические шаги",
                accent_blocks=[
                    ReportAccentBlock(
                        title="Фокус проверки гипотез",
                        points=[
                            "Определите один сценарий и критерий результата.",
                            "Проведите короткий тест 2–4 недели и зафиксируйте выводы.",
                        ],
                    )
                ],
            )
        )

    def _append_t3_cover(self, sections: list[ReportSection]) -> None:
        if not sections:
            return
        sections.insert(
            0,
            ReportSection(
                title="Титульный лист T3",
                paragraphs=[
                    "Расширенный формат отчёта: усиленные визуальные блоки, ключевые ориентиры и план действий.",
                ],
                accent_blocks=[
                    ReportAccentBlock(
                        title="Что внутри",
                        points=[
                            "Ключевые выводы и приоритеты.",
                            "Сценарии с акцентом на применение навыков.",
                            "План действий на месяц и год.",
                        ],
                    )
                ],
            )
        )


report_document_builder = ReportDocumentBuilder()
