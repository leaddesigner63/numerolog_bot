from app.core.config import Settings
from app.db.models import Order, OrderStatus, PaymentProvider, Tariff
from app.payments.prodamus import ProdamusProvider


def test_create_payment_link_handles_order_without_optional_contact_fields() -> None:
    settings = Settings(prodamus_form_url="https://pay.example/prodamus")
    provider = ProdamusProvider(settings)
    order = Order(
        id=999,
        user_id=1,
        tariff=Tariff.T1,
        amount=1000.00,
        currency="RUB",
        provider=PaymentProvider.PRODAMUS,
        status=OrderStatus.CREATED,
    )

    payment_link = provider.create_payment_link(order)

    assert payment_link is not None
    assert "order_id=999" in payment_link.url
    assert "products%5B0%5D%5Bname%5D=%D0%A2%D0%B0%D1%80%D0%B8%D1%84+T1" in payment_link.url
