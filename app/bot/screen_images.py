from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings

TARIFF_SENSITIVE_SCREENS: set[str] = {
    "S2",
    "S3",
    "S4",
    "S5",
    "S6",
    "S7",
    "S13",
    "S14",
    "S15",
}


def _resolve_tariff(screen_id: str, state: dict[str, Any]) -> str | None:
    if screen_id in {"S13", "S14"}:
        report_meta = state.get("report_meta") or {}
        tariff = report_meta.get("tariff")
        return str(tariff) if tariff else None
    selected_tariff = state.get("selected_tariff")
    return str(selected_tariff) if selected_tariff else None


def resolve_screen_image_path(screen_id: str, state: dict[str, Any]) -> Path | None:
    base_dir_value = settings.screen_images_dir
    if not base_dir_value:
        return None
    base_dir = Path(base_dir_value)
    if not base_dir.is_absolute():
        base_dir = (Path(__file__).resolve().parents[2] / base_dir_value).resolve()
    if not base_dir.is_dir():
        return None

    target_dir = base_dir / screen_id
    if screen_id in TARIFF_SENSITIVE_SCREENS:
        tariff = _resolve_tariff(screen_id, state)
        if not tariff:
            return None
        target_dir = base_dir / f"{screen_id}_{tariff}"

    if not target_dir.is_dir():
        return None

    allowed_suffixes = {".png", ".jpg", ".jpeg", ".webp"}
    for item in sorted(target_dir.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_file() and item.suffix.lower() in allowed_suffixes:
            return item
    return None
