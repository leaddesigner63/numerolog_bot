from __future__ import annotations

import html
import logging
import re

logger = logging.getLogger(__name__)

_REPORT_BR_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_REPORT_ANY_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9:_-]*(?:\s[^<>]*)?>")


def build_canonical_report_text(raw_text: str, tariff: str) -> str:
    """Возвращает единый канонический текст отчёта для TG и PDF."""
    if not raw_text:
        return ""

    decoded_text = raw_text
    for _ in range(3):
        unescaped = html.unescape(decoded_text)
        if unescaped == decoded_text:
            break
        decoded_text = unescaped

    normalized_breaks = _REPORT_BR_TAG_RE.sub("\n", decoded_text)
    without_tags = re.sub(r"</?[A-Za-z][^>\n]*>", "", normalized_breaks)
    without_known_tags = _REPORT_ANY_TAG_RE.sub("", without_tags)
    without_dangling_tags = re.sub(
        r"</?[A-Za-z][A-Za-z0-9:_-]*(?:\s*>)?",
        "",
        without_known_tags,
    )
    cleaned = without_dangling_tags.replace("<", "").replace(">", "")

    if cleaned != raw_text:
        logger.warning(
            "report_text_postprocess_quality_incident",
            extra={
                "tariff": tariff,
                "original_length": len(raw_text),
                "cleaned_length": len(cleaned),
            },
        )

    return cleaned
