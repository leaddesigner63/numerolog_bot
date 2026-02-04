from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


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
