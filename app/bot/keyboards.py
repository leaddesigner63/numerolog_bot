from __future__ import annotations

from aiogram.types import InlineKeyboardButton

_LONG_BUTTON_TEXT_THRESHOLD = 10
_MAX_BUTTONS_PER_LONG_TEXT_ROW = 2


def _button_label_length(button: InlineKeyboardButton) -> int:
    text = (button.text or "").strip()
    if not text:
        return 0
    parts = text.split(maxsplit=1)
    if len(parts) == 2 and len(parts[0]) <= 2:
        return len(parts[1])
    return len(text)


def enforce_long_button_rows(
    rows: list[list[InlineKeyboardButton]],
    *,
    long_text_threshold: int = _LONG_BUTTON_TEXT_THRESHOLD,
    max_buttons_per_row: int = _MAX_BUTTONS_PER_LONG_TEXT_ROW,
) -> list[list[InlineKeyboardButton]]:
    normalized_rows: list[list[InlineKeyboardButton]] = []
    safe_max_buttons = max(1, max_buttons_per_row)
    safe_threshold = max(1, long_text_threshold)

    for row in rows:
        if len(row) <= safe_max_buttons:
            normalized_rows.append(row)
            continue

        has_long_text_button = any(
            _button_label_length(button) > safe_threshold for button in row
        )
        if not has_long_text_button:
            normalized_rows.append(row)
            continue

        for index in range(0, len(row), safe_max_buttons):
            normalized_rows.append(row[index : index + safe_max_buttons])

    return normalized_rows
