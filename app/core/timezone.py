from __future__ import annotations

from datetime import datetime, timedelta, timezone

APP_TIMEZONE = timezone(timedelta(hours=3), name="GMT+3")
APP_TIMEZONE_LABEL = "GMT+3"


def now_app_timezone() -> datetime:
    return datetime.now(APP_TIMEZONE)


def as_app_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(APP_TIMEZONE)


def format_app_datetime(value: datetime, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return f"{as_app_timezone(value).strftime(fmt)} {APP_TIMEZONE_LABEL}"
