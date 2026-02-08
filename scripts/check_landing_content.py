#!/usr/bin/env python3
"""Статическая проверка контента лендинга по правилам из TZ.md."""

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--content",
        default="web/content/landing-content.json",
        help="Путь до JSON-контента лендинга",
    )
    args = parser.parse_args()

    content_path = Path(args.content)
    if not content_path.exists():
        print(f"[ERROR] Файл контента не найден: {content_path}")
        return 2

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

    print("[OK] Проверка контента лендинга пройдена.")
    print("[OK] Запрещённые слова не обнаружены (с учётом allowlist).")
    print("[OK] Красные зоны не обнаружены.")
    print("[OK] Все обязательные дисклеймеры присутствуют.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
