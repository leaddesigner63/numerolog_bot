from __future__ import annotations

from app.core.config import settings
from app.db.models import PaymentProvider as PaymentProviderEnum
from app.payments.base import PaymentProvider
from app.payments.cloudpayments import CloudPaymentsProvider
from app.payments.prodamus import ProdamusProvider


def get_payment_provider(provider_name: str | None = None) -> PaymentProvider:
    name = (provider_name or settings.payment_provider).lower()
    if name == PaymentProviderEnum.CLOUDPAYMENTS.value:
        return CloudPaymentsProvider(settings)
    return ProdamusProvider(settings)
