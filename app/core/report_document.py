from __future__ import annotations

from dataclasses import dataclass, field
import html
import re
from typing import Any

from app.db.models import Tariff
from app.core.tariff_labels import tariff_report_title


SUBSECTION_CONTRACT_PREFIX = "[[subsection]] "


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

    _MARKDOWN_MARKERS_RE = re.compile(r"(\*\*|__|`|~~)")
    _HEADING_PREFIX_RE = re.compile(r"^#+\s*")
    _LEADING_SYMBOL_RE = re.compile(r"^[^\wА-Яа-яЁё0-9]+")
    _BR_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
    _HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>\n]*>")
    _DANGLING_HTML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9:_-]*")
    _SERVICE_SECTION_TITLES = {
        "проверка данных",
        "техническая проверка",
        "валидация",
        "валидация данных",
        "диагностика",
        "диагностика парсинга",
    }
    _SERVICE_BULLET_PATTERNS = (
        re.compile(r"^проверка\s+данных[\s.!?]*$", re.IGNORECASE),
        re.compile(r"\bне распознан[аоы]?\b", re.IGNORECASE),
        re.compile(r"\bне полностью заполнен[аоы]?\b", re.IGNORECASE),
        re.compile(r"\bошибк[аи]\s+парсинг[а-я]*\b", re.IGNORECASE),
        re.compile(r"\bне удалось распознать\b", re.IGNORECASE),
        re.compile(r"\bданные отсутствуют\b", re.IGNORECASE),
    )
    _PDF_PROMO_PHRASES = (
        "бесплатный превью-отчёт",
        "доступен раз в месяц",
        "это превью",
    )
    _SUBTITLE_ARTIFACT_TRIGGER = "персональный маршрут"
    _WARNING_LINE_PATTERNS = (
        re.compile(r"^внимание[.!?]*$", re.IGNORECASE),
        re.compile(r"^предупреждение[.!?]*$", re.IGNORECASE),
        re.compile(r"^важно[.!?]*$", re.IGNORECASE),
        re.compile(r"^осторожно[.!?]*$", re.IGNORECASE),
    )
    _TECHNICAL_SEPARATOR_RE = re.compile(r"^[-=_~]{3,}$")
    _TITLE_MAX_CHARS = 72
    _NARRATIVE_CONNECTORS = (
        "что",
        "как",
        "когда",
        "это",
        "потому что",
        "чтобы",
        "если",
        "котор",
        "поэтому",
    )
    _VERB_LIKE_WORD_RE = re.compile(
        r"(?i)(ться|тись|ешь|ете|ем|им|ут|ют|ешься|ется|ются|ится|ится|ал|ала|али|ило|или|ать|ять|ить|еть|уть|лся|лась|лись)$"
    )
    _TIMELINE_LINE_RE = re.compile(
        r"(?i)^\s*(?:недел(?:я|и|ю|е|ь)|месяц(?:а|ев)?|(?:1\s*[–—-]\s*3|4\s*[–—-]\s*6|7\s*[–—-]\s*9|10\s*[–—-]\s*12))\b"
    )
    _TIMELINE_HEADER_RE = re.compile(r"(?i)\(по\s+неделям\):$|\(помесячно\):$")

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
            lines = self._merge_multiline_paragraphs(lines)
            non_empty = [line for line in lines if line]
            if not non_empty:
                return None

            normalized_title = self._sanitize_line(non_empty[0])
            title = normalized_title[:140] if len(normalized_title) > 6 else self._DEFAULT_TITLE
            subtitle = tariff_report_title(tariff_value, fallback=tariff_value)

            key_findings: list[str] = []
            sections: list[ReportSection] = []
            current = ReportSection(title="")
            allow_key_findings = True

            for raw_line in non_empty[1:]:
                stripped_raw = (raw_line or "").strip()
                is_explicit_subsection_line = bool(current.title) and stripped_raw.startswith("##")
                is_title = self._is_title(raw_line) and not is_explicit_subsection_line
                if (
                    is_title
                    and current.title
                    and not (current.paragraphs or current.bullets or current.accent_blocks)
                    and not self._is_explicit_title_marker(raw_line)
                ):
                    is_title = False
                if is_title:
                    if current.paragraphs or current.bullets or current.accent_blocks:
                        sections.append(current)
                    current = ReportSection(title=self._sanitize_line(raw_line.rstrip(":")))
                    allow_key_findings = False
                    continue
                bullet = self._extract_bullet(raw_line)
                if bullet is not None:
                    if allow_key_findings and len(key_findings) < 6 and not sections and not current.paragraphs:
                        key_findings.append(bullet)
                    else:
                        current.bullets.append(bullet)
                    continue
                if raw_line.lower().startswith("дисклеймер"):
                    continue
                allow_key_findings = False
                sanitized_paragraph = self._sanitize_line(raw_line)
                current.paragraphs.append(self._apply_subsection_contract(raw_line, sanitized_paragraph))

            if current.paragraphs or current.bullets or current.accent_blocks:
                sections.append(current)

            sections, key_findings = self._filter_service_content(sections, key_findings)

            if not key_findings:
                key_findings = [
                    point
                    for section in sections
                    for point in section.bullets[:2]
                ][:5]

            if tariff_value in {"T2", "T3"}:
                self._append_focus_block(sections)
            sections, key_findings = self._strip_pdf_promotions(sections, key_findings)
            sections, key_findings = self._strip_subtitle_artifacts(
                sections,
                key_findings,
                subtitle=subtitle,
                title=title,
            )
            if not key_findings:
                key_findings = [
                    point
                    for section in sections
                    for point in section.bullets[:2]
                ][:5]

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

    def _merge_multiline_paragraphs(self, lines: list[str]) -> list[str]:
        merged: list[str] = []
        paragraph_parts: list[str] = []
        preserve_next_timeline_line = False

        def flush_paragraph() -> None:
            if paragraph_parts:
                merged.append(" ".join(paragraph_parts))
                paragraph_parts.clear()

        for index, line in enumerate(lines):
            current = (line or "").strip()
            if not current:
                flush_paragraph()
                merged.append("")
                continue

            if preserve_next_timeline_line:
                flush_paragraph()
                merged.append(current)
                preserve_next_timeline_line = False
                continue

            next_line = (lines[index + 1] if index + 1 < len(lines) else "").strip()

            if self._is_timeline_line(current):
                flush_paragraph()
                merged.append(current)
                continue

            if (
                self._is_explicit_title_marker(current)
                or self._extract_bullet(current) is not None
                or self._is_technical_separator(current)
                or (not paragraph_parts and self._is_probable_standalone_title(current, next_line))
            ):
                flush_paragraph()
                merged.append(current)
                preserve_next_timeline_line = self._is_timeline_header(current)
                continue

            if paragraph_parts and self._ends_with_sentence_break(paragraph_parts[-1]):
                flush_paragraph()

            paragraph_parts.append(current)

        flush_paragraph()
        return merged

    def _is_timeline_line(self, line: str) -> bool:
        return bool(self._TIMELINE_LINE_RE.match((line or "").strip()))

    def _is_timeline_header(self, line: str) -> bool:
        return bool(self._TIMELINE_HEADER_RE.search((line or "").strip()))



    def _is_probable_standalone_title(self, current: str, next_line: str) -> bool:
        return bool(next_line) and self._is_title(current) and self._ends_with_sentence_break(next_line)

    def _ends_with_sentence_break(self, line: str) -> bool:
        stripped = (line or "").rstrip()
        return stripped.endswith((".", "!", "?", ":", ";"))

    def _is_explicit_title_marker(self, line: str) -> bool:
        stripped = (line or "").strip()
        return bool(stripped) and (stripped.startswith("#") or stripped.endswith(":"))

    def _is_technical_separator(self, line: str) -> bool:
        normalized = "".join((line or "").split())
        return bool(self._TECHNICAL_SEPARATOR_RE.match(normalized))

    def _resolve_tariff_value(self, tariff: Tariff | str | None) -> str:
        if isinstance(tariff, Tariff):
            return tariff.value
        raw = str(tariff or "T1")
        return raw if raw in {"T0", "T1", "T2", "T3"} else "T1"

    def _is_title(self, line: str) -> bool:
        raw = line.strip()
        if not raw:
            return False
        if self._extract_bullet(raw) is not None:
            return False

        sanitized = self._sanitize_line(raw)
        if not sanitized:
            return False
        if self._is_warning_line(sanitized):
            return False

        if raw.startswith("##") or raw.endswith(":"):
            return True

        # Важно: эти правила намеренно отсекают обычные абзацы,
        # чтобы не "перекрашивать" их в section/subsection style.
        if len(sanitized) > self._TITLE_MAX_CHARS:
            return False

        words_count = len(sanitized.split())
        if words_count < 2 or words_count > 6:
            return False

        normalized = f" {sanitized.lower()} "
        if words_count >= 5 and any(f" {marker} " in normalized for marker in self._NARRATIVE_CONNECTORS):
            return False

        punctuation_count = len(re.findall(r"[.!?:;,]", sanitized))
        if punctuation_count > 1 or "," in sanitized or ";" in sanitized:
            return False
        if sanitized.endswith("."):
            return False
        if sanitized.endswith(("?", "!")):
            return False
        if punctuation_count != 0:
            return False

        return self._looks_like_nominal_title(sanitized)

    def _looks_like_nominal_title(self, line: str) -> bool:
        words = [word for word in re.findall(r"[А-Яа-яЁёA-Za-z-]+", line) if len(word) > 1]
        if not words or len(words) > 6:
            return False

        for word in words:
            if self._VERB_LIKE_WORD_RE.search(word):
                return False
        return True

    def _is_warning_line(self, line: str) -> bool:
        normalized = " ".join((line or "").lower().split())
        return any(pattern.match(normalized) for pattern in self._WARNING_LINE_PATTERNS)

    def _extract_bullet(self, line: str) -> str | None:
        stripped = line.strip()
        markers = ("- ", "• ", "* ")
        for marker in markers:
            if stripped.startswith(marker):
                return self._sanitize_line(stripped[len(marker) :].strip())
        if len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in {")", "."}:
            return self._sanitize_line(stripped[2:].strip())
        return None

    def _sanitize_line(self, line: str) -> str:
        decoded = (line or "").replace("\u00a0", " ").strip()
        for _ in range(3):
            unescaped = html.unescape(decoded)
            if unescaped == decoded:
                break
            decoded = unescaped

        cleaned = self._BR_TAG_RE.sub(" ", decoded)
        cleaned = self._HTML_TAG_RE.sub("", cleaned)
        cleaned = self._DANGLING_HTML_TAG_RE.sub("", cleaned)
        cleaned = cleaned.replace("<", "").replace(">", "")
        cleaned = self._HEADING_PREFIX_RE.sub("", cleaned)
        cleaned = self._MARKDOWN_MARKERS_RE.sub("", cleaned)
        cleaned = self._LEADING_SYMBOL_RE.sub("", cleaned).strip()
        return " ".join(cleaned.split())

    def _extract_disclaimer(self, text: str) -> str:
        lowered = text.lower()
        if "сервис не является" in lowered:
            tail = text[lowered.index("сервис не является") :]
            return " ".join(tail.splitlines())[:500]
        return self._DEFAULT_DISCLAIMER

    def _apply_subsection_contract(self, raw_line: str, sanitized_line: str) -> str:
        stripped = (raw_line or "").strip()
        if not stripped.startswith("##"):
            return sanitized_line

        subsection_payload = self._sanitize_line(stripped.lstrip("#").strip())
        if not subsection_payload:
            return sanitized_line

        return f"{SUBSECTION_CONTRACT_PREFIX}{subsection_payload}"

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

    def _filter_service_content(
        self,
        sections: list[ReportSection],
        key_findings: list[str],
    ) -> tuple[list[ReportSection], list[str]]:
        filtered_sections: list[ReportSection] = []
        for section in sections:
            if self._is_service_section_title(section.title):
                continue
            bullets = [bullet for bullet in section.bullets if not self._is_service_bullet(bullet)]
            paragraphs = [paragraph for paragraph in section.paragraphs if not self._is_service_bullet(paragraph)]
            if bullets or paragraphs or section.accent_blocks:
                filtered_sections.append(
                    ReportSection(
                        title=section.title,
                        bullets=bullets,
                        paragraphs=paragraphs,
                        accent_blocks=section.accent_blocks,
                    )
                )

        filtered_findings = [point for point in key_findings if not self._is_service_bullet(point)]
        return filtered_sections, filtered_findings

    def _is_service_section_title(self, title: str) -> bool:
        normalized = " ".join((title or "").lower().replace("ё", "е").split()).rstrip(":")
        return normalized in self._SERVICE_SECTION_TITLES

    def _is_service_bullet(self, text: str) -> bool:
        normalized = " ".join((text or "").lower().replace("ё", "е").split())
        return any(pattern.search(normalized) for pattern in self._SERVICE_BULLET_PATTERNS)

    def _strip_pdf_promotions(
        self,
        sections: list[ReportSection],
        key_findings: list[str],
    ) -> tuple[list[ReportSection], list[str]]:
        cleaned_sections: list[ReportSection] = []
        for section in sections:
            cleaned_bullets = self._strip_pdf_promotions_from_items(section.bullets)
            cleaned_paragraphs = self._strip_pdf_promotions_from_items(section.paragraphs)
            if cleaned_bullets or cleaned_paragraphs or section.accent_blocks:
                cleaned_sections.append(
                    ReportSection(
                        title=section.title,
                        bullets=cleaned_bullets,
                        paragraphs=cleaned_paragraphs,
                        accent_blocks=section.accent_blocks,
                    )
                )
        cleaned_findings = self._strip_pdf_promotions_from_items(key_findings)
        return cleaned_sections, cleaned_findings

    def _strip_pdf_promotions_from_items(self, items: list[str]) -> list[str]:
        cleaned_items: list[str] = []
        for item in items:
            cleaned = item or ""
            for phrase in self._PDF_PROMO_PHRASES:
                cleaned = re.sub(re.escape(phrase), " ", cleaned, flags=re.IGNORECASE)
            cleaned = " ".join(cleaned.split()).strip(" -–—,:;")
            if cleaned:
                cleaned_items.append(cleaned)
        return cleaned_items

    def _strip_subtitle_artifacts(
        self,
        sections: list[ReportSection],
        key_findings: list[str],
        *,
        subtitle: str,
        title: str,
    ) -> tuple[list[ReportSection], list[str]]:
        def should_drop(line: str) -> bool:
            normalized = self._normalize_artifact_line(line)
            if not normalized or self._SUBTITLE_ARTIFACT_TRIGGER not in normalized:
                return False
            return any(
                token and token in normalized
                for token in (
                    self._normalize_artifact_line(subtitle),
                    self._normalize_artifact_line(title),
                )
            )

        cleaned_sections: list[ReportSection] = []
        for section in sections:
            cleaned_bullets = [bullet for bullet in section.bullets if not should_drop(bullet)]
            cleaned_paragraphs = [paragraph for paragraph in section.paragraphs if not should_drop(paragraph)]
            cleaned_title = "" if should_drop(section.title) else section.title
            if cleaned_title or cleaned_bullets or cleaned_paragraphs or section.accent_blocks:
                cleaned_sections.append(
                    ReportSection(
                        title=cleaned_title,
                        bullets=cleaned_bullets,
                        paragraphs=cleaned_paragraphs,
                        accent_blocks=section.accent_blocks,
                    )
                )

        cleaned_findings = [point for point in key_findings if not should_drop(point)]
        return cleaned_sections, cleaned_findings

    def _normalize_artifact_line(self, line: str) -> str:
        lowered = self._sanitize_line(line).lower()
        if not lowered:
            return ""
        compact = re.sub(r"[«»\"'`]+", "", lowered)
        compact = re.sub(r"\s*[—-]\s*", " ", compact)
        return re.sub(r"\s+", " ", compact).strip()


report_document_builder = ReportDocumentBuilder()
