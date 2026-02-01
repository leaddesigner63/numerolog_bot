from __future__ import annotations

import base64
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
class CloudPaymentsWebhook:
    order_id: int
    transaction_id: str | None
    status: str | None


class CloudPaymentsProvider(PaymentProvider):
    provider = PaymentProviderEnum.CLOUDPAYMENTS

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = logging.getLogger(__name__)

    def create_payment_link(self, order: Order, user: User | None = None) -> PaymentLink | None:
        if not self._settings.cloudpayments_public_id:
            self._logger.warning(
                "cloudpayments_public_id_missing",
                extra={"order_id": order.id, "user_id": getattr(user, "id", None)},
            )
            return None
        params = {
            "publicId": self._settings.cloudpayments_public_id,
            "invoiceId": str(order.id),
            "description": f"Тариф {order.tariff.value}",
            "amount": f"{order.amount:.2f}",
            "currency": order.currency,
        }
        if user:
            params["accountId"] = str(user.telegram_user_id)
        url = f"https://widget.cloudpayments.ru/?" f"{urlencode(params)}"
        return PaymentLink(url=url)

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookResult:
        secret = self._settings.cloudpayments_api_secret
        if not secret:
            self._logger.warning("cloudpayments_api_secret_missing")
            raise ValueError("CLOUDPAYMENTS_API_SECRET is not configured")
        signature = _find_signature(headers)
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
        expected_hex = expected.hex()
        expected_b64 = base64.b64encode(expected).decode("utf-8")
        if not signature or (
            not hmac.compare_digest(signature, expected_hex)
            and not hmac.compare_digest(signature, expected_b64)
        ):
            raise ValueError("Invalid CloudPayments signature")
        payload = _parse_payload(raw_body)
        webhook = _extract_webhook(payload)
        return WebhookResult(
            order_id=webhook.order_id,
            provider_payment_id=webhook.transaction_id,
            is_paid=_is_paid_status(webhook.status),
        )

    def check_payment_status(self, order: Order) -> WebhookResult | None:
        public_id = self._settings.cloudpayments_public_id
        api_secret = self._settings.cloudpayments_api_secret
        if not public_id or not api_secret:
            self._logger.warning(
                "cloudpayments_status_config_missing",
                extra={
                    "order_id": order.id,
                    "public_id_set": bool(public_id),
                    "api_secret_set": bool(api_secret),
                },
            )
            return None
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    "https://api.cloudpayments.ru/payments/find",
                    json={"InvoiceId": str(order.id)},
                    auth=(public_id, api_secret),
                )
                response.raise_for_status()
        except httpx.RequestError:
            return None
        except httpx.HTTPStatusError:
            return None
        data = _safe_json(response)
        model = data.get("Model") if isinstance(data, dict) else None
        status_value = None
        transaction_id = None
        if isinstance(model, dict):
            status_value = model.get("Status")
            transaction_id = model.get("TransactionId")
        if isinstance(status_value, str):
            status_str = status_value
        else:
            status_str = None
        return WebhookResult(
            order_id=order.id,
            provider_payment_id=str(transaction_id) if transaction_id else None,
            is_paid=_is_paid_status(status_str),
        )


def _find_signature(headers: Mapping[str, str]) -> str | None:
    lowered = {key.lower(): value for key, value in headers.items()}
    for key in ("content-hmac", "x-content-hmac", "x-cloudpayments-signature"):
        if key in lowered:
            return lowered[key]
    return None


def _parse_payload(raw_body: bytes) -> dict[str, Any]:
    try:
        return json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def _extract_webhook(payload: Mapping[str, Any]) -> CloudPaymentsWebhook:
    order_id = payload.get("InvoiceId") or payload.get("invoiceId")
    if order_id is None:
        raise ValueError("InvoiceId is missing in CloudPayments payload")
    transaction_id = payload.get("TransactionId") or payload.get("transactionId")
    status = payload.get("Status") or payload.get("status")
    return CloudPaymentsWebhook(
        order_id=int(order_id), transaction_id=transaction_id, status=status
    )


def _is_paid_status(status: str | None) -> bool:
    if not status:
        return False
    return status.lower() in {"completed", "authorized", "paid", "success", "succeeded"}


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return data
    return {}
