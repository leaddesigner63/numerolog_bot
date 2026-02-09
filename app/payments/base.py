from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Mapping

from app.db.models import Order, PaymentProvider as PaymentProviderEnum, User


@dataclass(frozen=True)
class PaymentLink:
    url: str
    provider: PaymentProviderEnum | None = None


# Backward-compatible alias used by payment providers.
PaymentLinkResult = PaymentLink


@dataclass(frozen=True)
class WebhookResult:
    order_id: int
    provider_payment_id: str | None
    is_paid: bool
    status: str | None = None
    verified: bool = False
    ok: bool = True


class PaymentProvider(abc.ABC):
    provider: PaymentProviderEnum

    @abc.abstractmethod
    def create_payment_link(self, order: Order, user: User | None = None) -> PaymentLink | None:
        raise NotImplementedError

    @abc.abstractmethod
    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookResult:
        raise NotImplementedError

    @abc.abstractmethod
    def check_payment_status(self, order: Order) -> WebhookResult | None:
        raise NotImplementedError
