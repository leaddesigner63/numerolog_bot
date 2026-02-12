from __future__ import annotations

from typing import Final


TARIFF_BUTTON_TITLES: Final[dict[str, str]] = {
    "T0": "Твоё новое начало (бесплатно)",
    "T1": "В чём твоя сила?",
    "T2": "Где твои деньги?",
    "T3": "Твой путь к себе!",
}


def tariff_button_title(tariff: str | None, fallback: str = "") -> str:
    if not tariff:
        return fallback
    return TARIFF_BUTTON_TITLES.get(str(tariff), str(tariff))

