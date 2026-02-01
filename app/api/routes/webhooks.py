from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import settings
from app.db.models import Order, OrderStatus, PaymentProvider as PaymentProviderEnum
from app.db.session import get_session
from app.payments import get_payment_provider


router = APIRouter(tags=["payments"])


@router.post("/webhooks/payments")
async def handle_payment_webhook(request: Request) -> dict[str, str]:
    raw_body = await request.body()
    provider_name = request.query_params.get("provider")
    provider = get_payment_provider(provider_name)

    try:
        result = provider.verify_webhook(raw_body, request.headers)
    except ValueError as exc:
        if provider_name:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
            ) from exc
        fallback_provider_name = (
            PaymentProviderEnum.CLOUDPAYMENTS.value
            if provider.provider == PaymentProviderEnum.PRODAMUS
            else PaymentProviderEnum.PRODAMUS.value
        )
        fallback_provider = get_payment_provider(fallback_provider_name)
        try:
            result = fallback_provider.verify_webhook(raw_body, request.headers)
            provider = fallback_provider
        except ValueError as fallback_exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=str(fallback_exc)
            ) from fallback_exc

    with get_session() as session:
        order = session.get(Order, result.order_id)
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        if result.is_paid:
            order.status = OrderStatus.PAID
            order.provider_payment_id = result.provider_payment_id
            order.paid_at = datetime.now(timezone.utc)
            order.provider = PaymentProviderEnum(provider.provider.value)
        else:
            order.status = OrderStatus.PENDING
    return {"status": "ok"}


@router.get("/webhooks/payments/provider")
async def get_payment_provider_info() -> dict[str, str | None]:
    return {
        "primary_provider": settings.payment_provider,
        "webhook_url": settings.payment_webhook_url,
    }
