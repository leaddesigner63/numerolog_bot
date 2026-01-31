from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Mapping

from app.db.models import Order, PaymentProvider as PaymentProviderEnum, User


@dataclass(frozen=True)
class PaymentLink:
    url: str


@dataclass(frozen=True)
class WebhookResult:
    order_id: int
    provider_payment_id: str | None
    is_paid: bool


class PaymentProvider(abc.ABC):
    provider: PaymentProviderEnum

    @abc.abstractmethod
    def create_payment_link(self, order: Order, user: User | None = None) -> PaymentLink | None:
        raise NotImplementedError

    @abc.abstractmethod
    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookResult:
        raise NotImplementedError
