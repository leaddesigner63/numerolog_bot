import re
from typing import Any
from urllib.parse import parse_qs, unquote_plus, urlparse

from sqlalchemy import select

from app.db.models import User, UserFirstTouchAttribution
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


def parse_first_touch_payload(payload: str | None) -> dict[str, Any]:
    raw_payload = payload or ""
    parsed_query_payload = ""
    if raw_payload:
        decoded_payload = unquote_plus(raw_payload)
        if "?" in decoded_payload:
            query = urlparse(decoded_payload).query
            if query:
                parsed_query_payload = (parse_qs(query).get("start") or [""])[0]
        if not parsed_query_payload and decoded_payload.startswith("start="):
            parsed_query_payload = decoded_payload.split("start=", maxsplit=1)[-1]
        if parsed_query_payload:
            raw_payload = parsed_query_payload
        else:
            raw_payload = decoded_payload

    raw_parts = raw_payload.split("_") if raw_payload else []

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

    with get_session() as session:
        user = session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        ).scalar_one_or_none()
        if user is None:
            session.add(User(telegram_user_id=telegram_user_id, telegram_username=telegram_username))
            session.flush()
        elif telegram_username is not None:
            user.telegram_username = telegram_username

        existing = session.execute(
            select(UserFirstTouchAttribution.id).where(
                UserFirstTouchAttribution.telegram_user_id == telegram_user_id
            )
        ).scalar_one_or_none()

        if existing is not None:
            return False

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

    return True
