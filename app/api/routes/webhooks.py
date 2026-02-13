from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import settings
from app.db.models import (
    Order,
    OrderStatus,
    PaymentConfirmationSource,
    PaymentProvider as PaymentProviderEnum,
)
from app.db.session import get_session
from app.payments import get_payment_provider
from app.payments.prodamus import _find_signature, _parse_payload


router = APIRouter(tags=["payments"])
logger = logging.getLogger(__name__)


def _candidate_providers(explicit: Optional[str]) -> list[str]:
    """Return provider names to try in order."""
    if explicit:
        return [explicit]

    primary = settings.payment_provider
    candidates: list[str] = [primary]

    # Add common alternates (avoid duplicates)
    for alt in (PaymentProviderEnum.PRODAMUS.value, PaymentProviderEnum.CLOUDPAYMENTS.value):
        if alt and alt not in candidates:
            candidates.append(alt)

    return candidates




def _payload_fingerprint(raw_body: bytes) -> str:
    if not raw_body:
        return "empty"
    return hashlib.sha256(raw_body).hexdigest()[:12]


def _signature_source(headers: dict[str, str], payload: dict[str, Any]) -> str:
    signature_data = _find_signature(headers, payload)
    if not signature_data:
        return "missing"
    return signature_data[1]


def _safe_payload(raw_body: bytes) -> dict[str, Any]:
    try:
        payload = _parse_payload(raw_body)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {}
    return {}

def _is_prodamus_probe(explicit_provider: Optional[str], raw_body: bytes, headers: dict[str, str]) -> bool:
    """Allow Prodamus test probe requests without payment data.

    Prodamus can send a connectivity check with `Sign: test` and arbitrary
    payload (for example `a=1`). This request does not contain `order_id`
    and must not affect order state.
    """
    if explicit_provider != PaymentProviderEnum.PRODAMUS.value:
        return False

    sign = headers.get("sign", "").strip().lower()
    if sign != "test":
        return False

    body = raw_body.decode("utf-8", errors="ignore")
    return "order_id" not in body


@router.post("/webhooks/payments")
async def handle_payment_webhook(request: Request) -> dict[str, str]:
    raw_body = await request.body()
    explicit_provider = request.query_params.get("provider")

    lowered_headers = {str(k).lower(): str(v) for k, v in request.headers.items()}
    if _is_prodamus_probe(explicit_provider, raw_body, lowered_headers):
        logger.info("prodamus_probe_webhook_accepted")
        return {"status": "ok"}

    last_exc: Optional[Exception] = None
    provider = None
    result = None

    for provider_name in _candidate_providers(explicit_provider):
        try:
            provider = get_payment_provider(provider_name)
            result = provider.verify_webhook(raw_body, request.headers)
            # Some providers may return result.ok=False instead of raising
            if getattr(result, "ok", True) is False:
                raise ValueError("Webhook verification failed")
            break
        except Exception as exc:  # noqa: BLE001 - webhook endpoint must be tolerant
            last_exc = exc
            safe_payload = _safe_payload(raw_body)
            logger.warning(
                "payment_webhook_verify_failed",
                extra={
                    "provider": provider_name,
                    "error": str(exc),
                    "fallback_attempt": explicit_provider is None,
                    "payload_fingerprint": _payload_fingerprint(raw_body),
                    "signature_source": _signature_source(lowered_headers, safe_payload),
                },
            )
            # If provider explicitly specified by query param, do not fallback
            if explicit_provider:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
                ) from exc
            continue

    if provider is None or result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(last_exc) if last_exc else "Invalid webhook",
        )

    order_id = getattr(result, "order_id", None)
    if order_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing order_id")

    is_paid = getattr(result, "is_paid", None)
    if is_paid is None:
        is_paid = bool(getattr(result, "paid", False))

    provider_payment_id = getattr(result, "provider_payment_id", None)

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

        if is_paid:
            now = datetime.now(timezone.utc)
            if order.status != OrderStatus.PAID:
                order.status = OrderStatus.PAID
                order.paid_at = now

            if not order.payment_confirmed_at:
                order.payment_confirmed_at = now
            order.payment_confirmation_source = PaymentConfirmationSource.PROVIDER_WEBHOOK
            order.payment_confirmed = True

            if provider_payment_id and not order.provider_payment_id:
                order.provider_payment_id = str(provider_payment_id)

            # Persist provider used to validate this webhook
            order.provider = PaymentProviderEnum(provider.provider.value)

        else:
            # Don't downgrade from PAID
            if order.status != OrderStatus.PAID:
                order.status = OrderStatus.PENDING

        session.add(order)
        session.commit()

    return {"status": "ok"}


@router.get("/webhooks/payments/provider")
async def get_payment_provider_info() -> dict[str, str | None]:
    return {
        "primary_provider": settings.payment_provider,
        "webhook_url": settings.payment_webhook_url,
    }
