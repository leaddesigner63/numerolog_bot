from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings

TARIFF_SENSITIVE_SCREENS: set[str] = {
    "S2",
    "S3",
    "S5",
    "S6",
    "S7",
    "S13",
    "S14",
    "S15",
}

S4_SCENARIO_STATE_KEY = "s4_image_scenario"
S4_SCENARIO_PROFILE = "profile"
S4_SCENARIO_AFTER_PAYMENT = "after_payment"


def _resolve_s4_scenario(state: dict[str, Any]) -> str:
    explicit = state.get(S4_SCENARIO_STATE_KEY)
    if isinstance(explicit, str):
        normalized = explicit.strip().lower()
        if normalized in {S4_SCENARIO_PROFILE, S4_SCENARIO_AFTER_PAYMENT}:
            return normalized

    order_status = state.get("order_status")
    if isinstance(order_status, str) and order_status.strip().lower() == "paid":
        return S4_SCENARIO_AFTER_PAYMENT

    profile_flow = state.get("profile_flow")
    if isinstance(profile_flow, str) and profile_flow.strip().lower() == "report":
        return S4_SCENARIO_AFTER_PAYMENT

    return S4_SCENARIO_PROFILE


def _resolve_s4_candidate_dirs(base_dir: Path, state: dict[str, Any]) -> list[Path]:
    scenario = _resolve_s4_scenario(state)
    scenario_token = "AFTER_PAYMENT" if scenario == S4_SCENARIO_AFTER_PAYMENT else "PROFILE"
    tariff = _resolve_tariff("S4", state)

    candidates: list[Path] = []
    if tariff:
        candidates.append(base_dir / f"S4_{scenario_token}_{tariff}")
    candidates.append(base_dir / f"S4_{scenario_token}")
    if tariff:
        candidates.append(base_dir / f"S4_{tariff}")
    candidates.append(base_dir / "S4")
    return candidates


def _resolve_tariff(screen_id: str, state: dict[str, Any]) -> str | None:
    if screen_id in {"S13", "S14"}:
        report_meta = state.get("report_meta") or {}
        tariff = report_meta.get("tariff")
        return str(tariff) if tariff else None
    selected_tariff = state.get("selected_tariff")
    return str(selected_tariff) if selected_tariff else None


def resolve_screen_image_path(screen_id: str, state: dict[str, Any]) -> Path | None:
    if screen_id == "S8":
        feedback_context = str(state.get("s8_context") or "").strip().lower()
        if feedback_context == "manual_payment_receipt":
            return None

    base_dir_value = settings.screen_images_dir
    if not base_dir_value:
        return None
    base_dir = Path(base_dir_value)
    if not base_dir.is_absolute():
        base_dir = (Path(__file__).resolve().parents[2] / base_dir_value).resolve()
    if not base_dir.is_dir():
        return None

    target_dirs = [base_dir / screen_id]
    if screen_id == "S4":
        target_dirs = _resolve_s4_candidate_dirs(base_dir, state)
    elif screen_id in TARIFF_SENSITIVE_SCREENS:
        tariff = _resolve_tariff(screen_id, state)
        if not tariff:
            return None
        target_dirs = [base_dir / f"{screen_id}_{tariff}"]

    allowed_suffixes = {".png", ".jpg", ".jpeg", ".webp"}
    for target_dir in target_dirs:
        if not target_dir.is_dir():
            continue
        for item in sorted(target_dir.iterdir()):
            if item.name.startswith("."):
                continue
            if item.is_file() and item.suffix.lower() in allowed_suffixes:
                return item
    return None
