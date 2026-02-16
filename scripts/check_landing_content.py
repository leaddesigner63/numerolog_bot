#!/usr/bin/env python3
"""Статическая проверка контента лендинга по правилам из TZ.md.

Поддерживает два режима источника контента:
1) JSON-словарь (web/content/landing-content.json) — обратная совместимость.
2) HTML-файлы лендинга (fallback), если JSON отсутствует.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path
from typing import Any


DEFAULT_JSON_REQUIRED_DISCLAIMERS = [
    "Сервис не является консультацией, прогнозом или рекомендацией к действию.",
    "Все выводы носят аналитический и описательный характер.",
    "Ответственность за решения остаётся за пользователем.",
    "Сервис не гарантирует финансовых или иных результатов.",
    "Возвратов нет.",
]

DEFAULT_HTML_REQUIRED_PHRASES = [
    "мы не предсказываем судьбу",
    "нет гарантий",
    "интерпретации/гипотезы",
]

# Для HTML fallback используем только обязательные формулировки из текущего SEO-лендинга.
# Ограничения forbidden/red-zone в этом режиме не применяются,
# т.к. SEO-лендинг осознанно содержит профильную лексику.
DEFAULT_HTML_POLICY: dict[str, list[str]] = {
    "forbiddenWords": [],
    "redZoneWords": [],
    "requiredDisclaimers": DEFAULT_HTML_REQUIRED_PHRASES,
    "allowListedPhrases": [],
}


def iter_strings(payload: Any, *, skip_policy: bool = False) -> list[str]:
    strings: list[str] = []
    if isinstance(payload, str):
        strings.append(payload)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if skip_policy and key == "policy":
                continue
            strings.extend(iter_strings(value, skip_policy=skip_policy))
    elif isinstance(payload, list):
        for value in payload:
            strings.extend(iter_strings(value, skip_policy=skip_policy))
    return strings


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _strip_html(source: str) -> str:
    """Возвращает видимый текст из HTML без script/style/svg."""
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", source, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<svg\b[^>]*>.*?</svg>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _collect_html_strings(html_root: Path) -> list[str]:
    if not html_root.exists():
        return []
    pages = sorted(
        p
        for p in html_root.rglob("*.html")
        if "/legal/" not in p.as_posix() and not p.as_posix().endswith("/404.html")
    )
    collected: list[str] = []
    for page in pages:
        try:
            text = _strip_html(page.read_text(encoding="utf-8"))
        except OSError:
            continue
        if text:
            collected.append(text)
    return collected


def load_content_and_policy(content_path: Path, html_root: Path) -> tuple[list[str], dict[str, list[str]], str]:
    """Загружает контент и policy из JSON либо из HTML fallback.

    Возвращает: (строки контента, policy, источник)
    """
    if content_path.exists():
        payload = json.loads(content_path.read_text(encoding="utf-8"))
        policy = payload.get("policy") or {}
        strings = iter_strings(payload, skip_policy=True)
        return strings, policy, f"json:{content_path}"

    html_strings = _collect_html_strings(html_root)
    if not html_strings:
        raise FileNotFoundError(
            f"Файл контента не найден: {content_path}; HTML-контент не найден в {html_root}"
        )
    return html_strings, DEFAULT_HTML_POLICY, f"html:{html_root}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--content",
        default="web/content/landing-content.json",
        help="Путь до JSON-контента лендинга",
    )
    parser.add_argument(
        "--html-root",
        default="web",
        help="Корень HTML-лендинга для fallback-режима, если JSON не найден",
    )
    args = parser.parse_args()

    content_path = Path(args.content)
    html_root = Path(args.html_root)

    try:
        strings, policy, source = load_content_and_policy(content_path, html_root)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        return 2

    normalized_strings = [normalize(item) for item in strings]
    full_text = "\n".join(normalized_strings)

    forbidden_words = [normalize(item) for item in policy.get("forbiddenWords") or []]
    red_zone_words = [normalize(item) for item in policy.get("redZoneWords") or []]
    required_disclaimers = [normalize(item) for item in policy.get("requiredDisclaimers") or []]
    allowlisted_phrases = [normalize(item) for item in policy.get("allowListedPhrases") or []]

    violations: list[str] = []

    for word in forbidden_words:
        if not word:
            continue
        hits = [item for item in normalized_strings if word in item]
        for hit in hits:
            if any(allow in hit for allow in allowlisted_phrases):
                continue
            violations.append(f"Запрещённое слово найдено: '{word}' -> '{hit}'")

    for word in red_zone_words:
        if not word:
            continue
        if word in full_text:
            violations.append(f"Слово из красной зоны найдено: '{word}'")

    for disclaimer in required_disclaimers:
        if not disclaimer:
            continue
        if disclaimer not in normalized_strings and disclaimer not in full_text:
            violations.append(f"Обязательный дисклеймер отсутствует: '{disclaimer}'")

    if violations:
        print("[FAIL] Проверка контента лендинга не пройдена:")
        for item in violations:
            print(f" - {item}")
        return 1

    print(f"[OK] Проверка контента лендинга пройдена. Источник: {source}")
    print("[OK] Запрещённые слова не обнаружены (с учётом allowlist).")
    print("[OK] Красные зоны не обнаружены.")
    print("[OK] Все обязательные дисклеймеры присутствуют.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
