from app.core.config import Settings
from app.db.models import Order, OrderStatus, PaymentProvider, Tariff, User
from app.payments.prodamus import ProdamusProvider


def test_prodamus_payment_link_contains_invoice_data() -> None:
    settings = Settings(
        prodamus_form_url="https://pay.example/prodamus",
        payment_webhook_url="https://bot.example/webhooks/payments",
    )
    provider = ProdamusProvider(settings)
    order = Order(
        id=101,
        user_id=1,
        tariff=Tariff.T2,
        amount=2990.00,
        currency="RUB",
        provider=PaymentProvider.PRODAMUS,
        status=OrderStatus.CREATED,
    )
    user = User(id=1, telegram_user_id=777000, telegram_username="demo_user")

    payment_link = provider.create_payment_link(order, user=user)

    assert payment_link is not None
    assert "order_id=101" in payment_link.url
    assert "order_num=101" in payment_link.url
    assert "invoice_id=101" in payment_link.url
    assert "amount=2990.00" in payment_link.url
    assert "sum=2990.00" in payment_link.url
    assert "products%5B0%5D%5Bname%5D=%D0%A2%D0%B0%D1%80%D0%B8%D1%84+T2" in payment_link.url
    assert "products%5B0%5D%5Bprice%5D=2990.00" in payment_link.url
    assert "products%5B0%5D%5Bquantity%5D=1" in payment_link.url
    assert "products%5B0%5D%5Bsum%5D=2990.00" in payment_link.url
    assert "callback_url=https%3A%2F%2Fbot.example%2Fwebhooks%2Fpayments" in payment_link.url
    assert "customer_id=777000" in payment_link.url
    assert "customer_username=demo_user" in payment_link.url
