#!/usr/bin/env python3
"""Статическая проверка контента лендинга.

Поддерживает 2 режима:
1) Исторический JSON-контент (`web/content/landing-content.json`).
2) Текущий HTML-сайт в каталоге `web/`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


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


def run_json_mode(content_path: Path) -> int:
    payload = json.loads(content_path.read_text(encoding="utf-8"))
    policy = payload.get("policy") or {}
    strings = iter_strings(payload, skip_policy=True)
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
        if disclaimer and disclaimer not in normalized_strings:
            violations.append(f"Обязательный дисклеймер отсутствует: '{disclaimer}'")

    if violations:
        print("[FAIL] Проверка контента лендинга не пройдена:")
        for item in violations:
            print(f" - {item}")
        return 1

    print("[OK] Проверка контента лендинга пройдена (JSON-режим).")
    return 0


def run_html_mode(web_dir: Path) -> int:
    required_files = [
        web_dir / "index.html",
        web_dir / "prices" / "index.html",
        web_dir / "faq" / "index.html",
        web_dir / "articles" / "index.html",
        web_dir / "contacts" / "index.html",
        web_dir / "legal" / "privacy" / "index.html",
        web_dir / "legal" / "offer" / "index.html",
        web_dir / "assets" / "css" / "styles.css",
        web_dir / "assets" / "js" / "script.js",
        web_dir / "assets" / "svg" / "sprite.svg",
        web_dir / "robots.txt",
        web_dir / "sitemap.xml",
        web_dir / "favicon.svg",
    ]

    missing = [str(path) for path in required_files if not path.exists()]
    if missing:
        print("[FAIL] Не найдены обязательные файлы сайта:")
        for item in missing:
            print(f" - {item}")
        return 1

    bad_markers = ("будет добавлено", "lorem ipsum", "todo", "tbd")
    html_files = sorted(web_dir.rglob("*.html"))

    violations: list[str] = []
    for html_file in html_files:
        text = normalize(html_file.read_text(encoding="utf-8"))
        for marker in bad_markers:
            if marker in text:
                violations.append(f"Плейсхолдер '{marker}' найден в {html_file}")

    if violations:
        print("[FAIL] Проверка контента лендинга не пройдена (HTML-режим):")
        for item in violations:
            print(f" - {item}")
        return 1

    print("[OK] Проверка контента лендинга пройдена (HTML-режим).")
    print("[OK] Обязательные файлы присутствуют.")
    print("[OK] Плейсхолдеры не найдены.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--content",
        default="web/content/landing-content.json",
        help="Путь до JSON-контента лендинга или каталог web/",
    )
    args = parser.parse_args()

    content_path = Path(args.content)
    if content_path.exists() and content_path.is_file() and content_path.suffix.lower() == ".json":
        return run_json_mode(content_path)

    web_dir = content_path if content_path.exists() and content_path.is_dir() else Path("web")
    if not web_dir.exists() or not web_dir.is_dir():
        print(f"[ERROR] Каталог сайта не найден: {web_dir}")
        return 2

    return run_html_mode(web_dir)


if __name__ == "__main__":
    sys.exit(main())
