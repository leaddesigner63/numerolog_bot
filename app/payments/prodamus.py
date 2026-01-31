from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlencode

from app.core.config import Settings
from app.db.models import Order, PaymentProvider as PaymentProviderEnum, User
from app.payments.base import PaymentLink, PaymentProvider, WebhookResult


@dataclass(frozen=True)
class ProdamusWebhook:
    order_id: int
    payment_id: str | None
    status: str | None


class ProdamusProvider(PaymentProvider):
    provider = PaymentProviderEnum.PRODAMUS

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_payment_link(self, order: Order, user: User | None = None) -> PaymentLink | None:
        if not self._settings.prodamus_form_url:
            return None
        description = f"Тариф {order.tariff.value}"
        params = {
            "order_id": str(order.id),
            "amount": f"{order.amount:.2f}",
            "currency": order.currency,
            "description": description,
        }
        if self._settings.payment_webhook_url:
            params["callback_url"] = self._settings.payment_webhook_url
        url = f"{self._settings.prodamus_form_url}?{urlencode(params)}"
        return PaymentLink(url=url)

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookResult:
        secret = self._settings.prodamus_webhook_secret
        if not secret:
            raise ValueError("PRODAMUS_WEBHOOK_SECRET is not configured")
        signature = _find_signature(headers, raw_body)
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid Prodamus signature")
        payload = _parse_payload(raw_body)
        webhook = _extract_webhook(payload)
        return WebhookResult(
            order_id=webhook.order_id,
            provider_payment_id=webhook.payment_id,
            is_paid=_is_paid_status(webhook.status),
        )


def _find_signature(headers: Mapping[str, str], raw_body: bytes) -> str | None:
    lowered = {key.lower(): value for key, value in headers.items()}
    for key in ("x-prodamus-signature", "x-signature", "x-webhook-signature"):
        if key in lowered:
            return lowered[key]
    payload = _parse_payload(raw_body)
    for key in ("signature", "sign"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return None


def _parse_payload(raw_body: bytes) -> dict[str, Any]:
    try:
        return json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        pass
    try:
        decoded = raw_body.decode("utf-8")
        pairs = [chunk.split("=", 1) for chunk in decoded.split("&") if chunk]
        return {key: value for key, value in pairs if len(key) > 0}
    except Exception:
        return {}


def _extract_webhook(payload: Mapping[str, Any]) -> ProdamusWebhook:
    order_id = payload.get("order_id") or payload.get("order") or payload.get("order_num")
    if order_id is None:
        raise ValueError("order_id is missing in Prodamus payload")
    payment_id = payload.get("payment_id") or payload.get("transaction_id")
    status = payload.get("status") or payload.get("payment_status")
    return ProdamusWebhook(order_id=int(order_id), payment_id=payment_id, status=status)


def _is_paid_status(status: str | None) -> bool:
    if not status:
        return False
    return status.lower() in {"paid", "success", "succeeded", "completed"}
