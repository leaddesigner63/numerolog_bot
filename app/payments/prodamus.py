from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode

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
            "amount": amount,
            "sum": amount,
            "description": description,
            "products[0][name]": description,
            "products[0][price]": amount,
            "products[0][quantity]": "1",
            "products[0][sum]": amount,
        }
        if self._settings.prodamus_unified_key:
            params["do"] = "link"
            params["key"] = self._settings.prodamus_unified_key
        if user:
            params["customer_id"] = str(user.telegram_user_id)
            if user.telegram_username:
                params["customer_username"] = user.telegram_username
        if self._settings.payment_webhook_url:
            params["callback_url"] = self._settings.payment_webhook_url
        if self._settings.payment_success_url:
            params["success_url"] = self._settings.payment_success_url
        if self._settings.payment_fail_url:
            params["fail_url"] = self._settings.payment_fail_url
        api_generated_link = self._create_api_generated_payment_link(params)
        if api_generated_link:
            return PaymentLink(url=api_generated_link)
        url = f"{self._settings.prodamus_form_url}?{urlencode(params)}"
        return PaymentLink(url=url)

    def _create_api_generated_payment_link(self, base_params: dict[str, str]) -> str | None:
        if not self._settings.prodamus_unified_key:
            return None

        api_params = dict(base_params)
        api_params["do"] = "link"
        api_params["key"] = self._settings.prodamus_unified_key

        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                response = client.get(self._settings.prodamus_form_url, params=api_params)
                response.raise_for_status()
        except httpx.HTTPError:
            return None

        return _extract_payment_link_from_response(response)

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookResult:
        secret = self._settings.prodamus_unified_key
        payload = _parse_payload(raw_body)
        if secret:
            signature_data = _find_signature(headers, payload)
            if signature_data:
                if not _matches_signature(
                    signature=signature_data[0],
                    secret=secret,
                    payload=payload,
                    raw_body=raw_body,
                ):
                    raise ValueError("Invalid Prodamus signature")
            elif not _matches_payload_secret(payload, secret):
                raise ValueError("Missing Prodamus signature")
        webhook = _extract_webhook(payload)
        return WebhookResult(
            order_id=webhook.order_id,
            provider_payment_id=webhook.payment_id,
            is_paid=_is_paid_status(webhook.status),
        )

    def check_payment_status(self, order: Order) -> WebhookResult | None:
        status_url = self._settings.prodamus_status_url or self._settings.prodamus_form_url
        secret = self._settings.prodamus_unified_key
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
        # Контракт status API: order_id + secret в теле запроса.
        # Используем form-urlencoded формат, чтобы соответствовать
        # типичному формату endpoint Prodamus.
        payload = {"order_id": str(order.id), "secret": secret}
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(status_url, data=payload)
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

def _find_signature(headers: Mapping[str, str], payload: Mapping[str, Any]) -> tuple[str, str] | None:
    lowered = {key.lower(): value for key, value in headers.items()}
    for key in (
        "x-prodamus-signature",
        "x-signature",
        "x-webhook-signature",
        "signature",
        "sign",
    ):
        if key in lowered:
            return lowered[key], "header"
    payload_signature = _extract_string_by_keys(payload, keys=("signature", "sign", "sig"))
    if payload_signature:
        return payload_signature, "payload"
    return None

def _matches_signature(
    signature: str,
    secret: str,
    payload: Mapping[str, Any],
    raw_body: bytes,
) -> bool:
    # Основной каноничный алгоритм из контракта: MD5(token + secret).
    canonical_signature = _canonical_signature(secret, payload)
    if canonical_signature and signature.casefold() == canonical_signature.casefold():
        return True

    hmac_digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    fallback_hmac_hex = hmac_digest.hex()
    fallback_hmac_base64 = base64.b64encode(hmac_digest).decode("utf-8")
    fallback_md5_secret_body = hashlib.md5(secret.encode("utf-8") + raw_body).hexdigest()
    fallback_md5_body_secret = hashlib.md5(raw_body + secret.encode("utf-8")).hexdigest()
    fallback_sha256 = hashlib.sha256(raw_body + secret.encode("utf-8")).hexdigest()
    for candidate in (
        fallback_hmac_hex,
        fallback_hmac_base64,
        fallback_md5_secret_body,
        fallback_md5_body_secret,
        fallback_sha256,
    ):
        if signature.casefold() == candidate.casefold():
            return True
    return False


def _matches_payload_secret(payload: Mapping[str, Any], secret: str) -> bool:
    candidates = _extract_strings_by_keys(
        payload,
        keys=("secret", "webhook_secret", "callback_secret", "merchant_secret", "password"),
    )
    if not candidates:
        return False
    return any(candidate == secret for candidate in candidates)

def _canonical_signature(secret: str, payload: Mapping[str, Any]) -> str | None:
    token = payload.get("token")
    if not isinstance(token, str) or not token:
        return None
    return hashlib.md5(f"{token}{secret}".encode("utf-8")).hexdigest()


def _parse_payload(raw_body: bytes) -> dict[str, Any]:
    try:
        return json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        pass
    try:
        decoded = raw_body.decode("utf-8")
        return {key: value for key, value in parse_qsl(decoded, keep_blank_values=True)}
    except Exception:
        return {}

def _extract_webhook(payload: Mapping[str, Any]) -> ProdamusWebhook:
    order_id = payload.get("order_id") or payload.get("order")
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
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _extract_payment_link_from_response(response: httpx.Response) -> str | None:
    data = _safe_json(response)
    for key in ("url", "link", "payment_url", "paymentLink"):
        value = data.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value

    body = response.text.strip()
    if body.startswith(("http://", "https://")):
        return body

    match = re.search(r"https?://[^\s\"'<>]+", body)
    if match:
        return match.group(0)
    return None

def _extract_status_value(payload: Mapping[str, Any]) -> str | None:
    return _extract_first_string(payload, keys=("status", "payment_status", "state"))

def _extract_payment_id_value(payload: Mapping[str, Any]) -> str | None:
    return _extract_first_string(
        payload,
        keys=("payment_id", "transaction_id", "id", "payment", "paymentId"),
    )


def _extract_string_by_keys(payload: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    values = _extract_strings_by_keys(payload, keys=keys)
    if values:
        return values[0]
    return None


def _extract_strings_by_keys(payload: Mapping[str, Any], keys: tuple[str, ...]) -> list[str]:
    normalized = {key.casefold() for key in keys}
    results: list[str] = []

    def _walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if key.casefold() in normalized:
                    if isinstance(nested, str) and nested:
                        results.append(nested)
                    elif isinstance(nested, (int, float)):
                        results.append(str(nested))
                _walk(nested)
            return
        if isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(payload)
    return results


def _extract_first_string(payload: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    direct = _extract_string_from_mapping(payload, keys)
    if direct:
        return direct

    for container_key in (
        "result",
        "data",
        "payment",
        "payments",
        "order",
        "invoice",
        "response",
    ):
        nested = payload.get(container_key)
        candidate = _extract_string_from_unknown(nested, keys)
        if candidate:
            return candidate
    return None


def _extract_string_from_unknown(value: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, Mapping):
        return _extract_first_string(value, keys)
    if isinstance(value, list):
        for item in value:
            candidate = _extract_string_from_unknown(item, keys)
            if candidate:
                return candidate
    return None


def _extract_string_from_mapping(payload: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, int):
            return str(value)
    return None
