from __future__ import annotations

from app.core.config import Settings
from app.db.models import Order, OrderStatus, PaymentProvider, Tariff
from app.payments.prodamus import ProdamusProvider


def _order() -> Order:
    return Order(
        id=777,
        user_id=1,
        tariff=Tariff.T1,
        amount=990.00,
        currency="RUB",
        provider=PaymentProvider.PRODAMUS,
        status=OrderStatus.CREATED,
    )


def test_prodamus_status_check_is_disabled_without_network_calls() -> None:
    settings = Settings(
        prodamus_form_url="https://pay.example/form",
        prodamus_key="single_key",
    )
    provider = ProdamusProvider(settings)

    result = provider.check_payment_status(_order())

    assert result is None
