import re
from typing import Any
from urllib.parse import parse_qs, unquote_plus, urlparse

from sqlalchemy import select

from app.db.models import User, UserFirstTouchAttribution, UserTouchEvent
from app.db.session import get_session


def _extract_marker_value(payload: str, marker: str, next_markers: tuple[str, ...]) -> str | None:
    if next_markers:
        next_expr = "|".join(re.escape(next_marker) for next_marker in next_markers)
        pattern = rf"{re.escape(marker)}(.*?)(?=(?:{next_expr})|$)"
    else:
        pattern = rf"{re.escape(marker)}(.*)$"
    match = re.search(pattern, payload)
    if not match:
        return None
    return match.group(1)


def _unwrap_start_payload(payload: str) -> str:
    if not payload:
        return ""

    parsed_url = urlparse(payload)
    if parsed_url.query:
        start_values = parse_qs(parsed_url.query, keep_blank_values=True).get("start")
        if start_values:
            return unquote_plus(start_values[0])

    if payload.startswith("start="):
        start_values = parse_qs(payload, keep_blank_values=True).get("start")
        if start_values:
            return unquote_plus(start_values[0])

    return unquote_plus(payload)


def _parse_exact_querystring_payload(raw_payload: str) -> tuple[str | None, str | None, str | None] | None:
    if not raw_payload or "=" not in raw_payload:
        return None

    parsed = parse_qs(raw_payload, keep_blank_values=True)
    if "src" not in parsed and "cmp" not in parsed and "pl" not in parsed:
        return None

    source = parsed.get("src", [None])[0]
    campaign = parsed.get("cmp", [None])[0]
    placement = parsed.get("pl", [None])[0]
    return source, campaign, placement


def parse_first_touch_payload(payload: str | None) -> dict[str, Any]:
    raw_payload = _unwrap_start_payload(payload or "")
    raw_parts = raw_payload.split("_") if raw_payload else []

    exact_querystring_values = _parse_exact_querystring_payload(raw_payload)
    if exact_querystring_values is not None:
        source, campaign, placement = exact_querystring_values
    else:
        source = _extract_marker_value(raw_payload, "src_", ("cmp_", "pl_"))
        campaign = _extract_marker_value(raw_payload, "cmp_", ("pl_",))
        placement = _extract_marker_value(raw_payload, "pl_", tuple())

        if source is None and campaign is None and placement is None:
            source = raw_parts[0] if len(raw_parts) > 0 and raw_parts[0] else None
            campaign = raw_parts[1] if len(raw_parts) > 1 and raw_parts[1] else None
            placement = "_".join(raw_parts[2:]) if len(raw_parts) > 2 else None

    return {
        "start_payload": raw_payload,
        "source": source,
        "campaign": campaign,
        "placement": placement,
        "raw_parts": raw_parts,
    }


def save_user_first_touch_attribution(
    telegram_user_id: int,
    payload: str | None,
    telegram_username: str | None = None,
) -> bool:
    parsed_payload = parse_first_touch_payload(payload)
    has_attribution_data = bool(
        parsed_payload.get("start_payload")
        or parsed_payload.get("source")
        or parsed_payload.get("campaign")
        or parsed_payload.get("placement")
    )

    with get_session() as session:
        user = session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        ).scalar_one_or_none()
        if user is None:
            session.add(User(telegram_user_id=telegram_user_id, telegram_username=telegram_username))
            session.flush()
        elif telegram_username is not None:
            user.telegram_username = telegram_username

        session.add(
            UserTouchEvent(
                telegram_user_id=telegram_user_id,
                start_payload=str(parsed_payload.get("start_payload") or ""),
                source=parsed_payload.get("source"),
                campaign=parsed_payload.get("campaign"),
                placement=parsed_payload.get("placement"),
            )
        )

        existing = session.execute(
            select(UserFirstTouchAttribution).where(
                UserFirstTouchAttribution.telegram_user_id == telegram_user_id
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                UserFirstTouchAttribution(
                    telegram_user_id=telegram_user_id,
                    start_payload=str(parsed_payload.get("start_payload") or ""),
                    source=parsed_payload.get("source"),
                    campaign=parsed_payload.get("campaign"),
                    placement=parsed_payload.get("placement"),
                    raw_parts=parsed_payload.get("raw_parts"),
                )
            )
            return has_attribution_data

        existing_is_empty = not (
            existing.start_payload
            or existing.source
            or existing.campaign
            or existing.placement
        )
        if not (existing_is_empty and has_attribution_data):
            return False

        existing.start_payload = str(parsed_payload.get("start_payload") or "")
        existing.source = parsed_payload.get("source")
        existing.campaign = parsed_payload.get("campaign")
        existing.placement = parsed_payload.get("placement")
        existing.raw_parts = parsed_payload.get("raw_parts")

    return True
