from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_FIRST_TOUCH_ATTRIBUTION_ERRORS_TOTAL = 0


def increment_first_touch_attribution_errors_total() -> int:
    global _FIRST_TOUCH_ATTRIBUTION_ERRORS_TOTAL
    _FIRST_TOUCH_ATTRIBUTION_ERRORS_TOTAL += 1
    return _FIRST_TOUCH_ATTRIBUTION_ERRORS_TOTAL


def get_first_touch_attribution_errors_total() -> int:
    return _FIRST_TOUCH_ATTRIBUTION_ERRORS_TOTAL


def reset_monitoring_counters() -> None:
    global _FIRST_TOUCH_ATTRIBUTION_ERRORS_TOTAL
    _FIRST_TOUCH_ATTRIBUTION_ERRORS_TOTAL = 0


async def send_monitoring_event(event: str, payload: dict) -> None:
    webhook_url = settings.monitoring_webhook_url
    if not webhook_url:
        return
    data = {"event": event, "payload": payload}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(webhook_url, json=data)
    except Exception as exc:
        logger.warning("monitoring_webhook_failed", extra={"event": event, "error": str(exc)})
