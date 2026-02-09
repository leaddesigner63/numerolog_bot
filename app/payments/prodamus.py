from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlencode

import httpx

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
        self._logger = logging.getLogger(__name__)

    def create_payment_link(self, order: Order, user: User | None = None) -> PaymentLink | None:
        if not self._settings.prodamus_form_url:
            self._logger.warning(
                "prodamus_form_url_missing",
                extra={"order_id": order.id, "user_id": getattr(user, "id", None)},
            )
            return None
        description = f"Тариф {order.tariff.value}"
        amount = f"{order.amount:.2f}"
        params = {
            "order_id": str(order.id),
            "order_num": str(order.id),
            "invoice_id": str(order.id),
            "amount": amount,
            "sum": amount,
            "currency": order.currency,
            "description": description,
            "products[0][name]": description,
            "products[0][price]": amount,
            "products[0][quantity]": "1",
            "products[0][sum]": amount,
        }
        if user:
            params["customer_id"] = str(user.telegram_user_id)
            if user.telegram_username:
                params["customer_username"] = user.telegram_username
        if self._settings.payment_webhook_url:
            params["callback_url"] = self._settings.payment_webhook_url
        url = f"{self._settings.prodamus_form_url}?{urlencode(params)}"
        return PaymentLink(url=url)

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookResult:
        secret = self._settings.prodamus_webhook_secret
        if not secret:
            self._logger.warning("prodamus_webhook_secret_missing")
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

    def check_payment_status(self, order: Order) -> WebhookResult | None:
        status_url = self._settings.prodamus_status_url
        secret = self._settings.prodamus_secret
        if not status_url or not secret:
            self._logger.warning(
                "prodamus_status_config_missing",
                extra={
                    "order_id": order.id,
                    "status_url_set": bool(status_url),
                    "secret_set": bool(secret),
                },
            )
            return None
        payload = {"order_id": str(order.id), "secret": secret}
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(status_url, json=payload)
                response.raise_for_status()
        except httpx.RequestError:
            return None
        except httpx.HTTPStatusError:
            return None
        data = _safe_json(response)
        status = _extract_status_value(data)
        payment_id = _extract_payment_id_value(data)
        return WebhookResult(
            order_id=order.id,
            provider_payment_id=payment_id,
            is_paid=_is_paid_status(status),
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


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _extract_status_value(payload: Mapping[str, Any]) -> str | None:
    for key in ("status", "payment_status"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    result = payload.get("result")
    if isinstance(result, dict):
        value = result.get("status")
        if isinstance(value, str):
            return value
    return None


def _extract_payment_id_value(payload: Mapping[str, Any]) -> str | None:
    for key in ("payment_id", "transaction_id"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    result = payload.get("result")
    if isinstance(result, dict):
        value = result.get("payment_id") or result.get("transaction_id")
        if isinstance(value, str):
            return value
    return None
