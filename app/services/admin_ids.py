from __future__ import annotations

from sqlalchemy import true

from app.core.config import settings


def parse_admin_ids(raw_value: str | None) -> set[int]:
    if not raw_value:
        return set()
    admin_ids: set[int] = set()
    for item in raw_value.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            admin_ids.add(int(candidate))
        except ValueError:
            continue
    return admin_ids


def exclude_admin_telegram_user_ids(column, raw_admin_ids: str | None = None):
    admin_ids = parse_admin_ids(settings.admin_ids if raw_admin_ids is None else raw_admin_ids)
    if not admin_ids:
        return true()
    return ~column.in_(admin_ids)
