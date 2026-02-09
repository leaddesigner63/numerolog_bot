from app.core.config import Settings
from app.db.models import Order, OrderStatus, PaymentProvider, Tariff, User
import hashlib

from app.payments.prodamus import ProdamusProvider

def test_prodamus_payment_link_contains_invoice_data() -> None:
    settings = Settings(
        prodamus_form_url="https://pay.example/prodamus",
        payment_webhook_url="https://bot.example/webhooks/payments",
        payment_success_url="https://bot.example/payments/success",
        payment_fail_url="https://bot.example/payments/fail",
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
    assert "amount=2990.00" in payment_link.url
    assert "sum=2990.00" in payment_link.url
    assert "currency=" not in payment_link.url
    assert "products%5B0%5D%5Bname%5D=%D0%A2%D0%B0%D1%80%D0%B8%D1%84+T2" in payment_link.url
    assert "products%5B0%5D%5Bprice%5D=2990.00" in payment_link.url
    assert "products%5B0%5D%5Bquantity%5D=1" in payment_link.url
    assert "products%5B0%5D%5Bsum%5D=2990.00" in payment_link.url
    assert "callback_url=https%3A%2F%2Fbot.example%2Fwebhooks%2Fpayments" in payment_link.url
    assert "success_url=https%3A%2F%2Fbot.example%2Fpayments%2Fsuccess" in payment_link.url
    assert "fail_url=https%3A%2F%2Fbot.example%2Fpayments%2Ffail" in payment_link.url
    assert "customer_id=777000" in payment_link.url
    assert "customer_username=demo_user" in payment_link.url

def test_prodamus_payment_link_includes_api_key_params() -> None:
    settings = Settings(
        prodamus_form_url="https://pay.example/prodamus",
        prodamus_api_key="test_api_key",
    )
    provider = ProdamusProvider(settings)
    order = Order(
        id=202,
        user_id=1,
        tariff=Tariff.T1,
        amount=990.00,
        currency="RUB",
        provider=PaymentProvider.PRODAMUS,
        status=OrderStatus.CREATED,
    )

    payment_link = provider.create_payment_link(order)

    assert payment_link is not None
    assert "do=link" in payment_link.url
    assert "key=test_api_key" in payment_link.url




def test_prodamus_payment_link_uses_unified_single_key() -> None:
    settings = Settings(
        prodamus_form_url="https://pay.example/prodamus",
        prodamus_key="single_key",
    )
    provider = ProdamusProvider(settings)
    order = Order(
        id=203,
        user_id=1,
        tariff=Tariff.T1,
        amount=990.00,
        currency="RUB",
        provider=PaymentProvider.PRODAMUS,
        status=OrderStatus.CREATED,
    )

    payment_link = provider.create_payment_link(order)

    assert payment_link is not None
    assert "do=link" in payment_link.url
    assert "key=single_key" in payment_link.url

def test_prodamus_payment_link_prefers_api_generated_link(monkeypatch) -> None:
    settings = Settings(
        prodamus_form_url="https://pay.example/prodamus",
        prodamus_api_key="test_api_key",
    )
    provider = ProdamusProvider(settings)
    order = Order(
        id=520,
        user_id=1,
        tariff=Tariff.T1,
        amount=560.00,
        currency="RUB",
        provider=PaymentProvider.PRODAMUS,
        status=OrderStatus.CREATED,
    )

    monkeypatch.setattr(
        provider,
        "_create_api_generated_payment_link",
        lambda base_params: "https://payform.ru/b7aCNPs/",
    )

    payment_link = provider.create_payment_link(order)

    assert payment_link is not None
    assert payment_link.url == "https://payform.ru/b7aCNPs/"

def test_prodamus_webhook_accepts_sign_with_api_key() -> None:
    api_key = "test_api_key"
    token = "abc123"
    sign = hashlib.md5(f"{token}{api_key}".encode("utf-8")).hexdigest()
    payload = (
        '{"order_id": "101", "status": "paid", "payment_id": "p-1", '
        f'"token": "{token}", "sign": "{sign}"'
        "}"
    ).encode("utf-8")
    settings = Settings(prodamus_api_key=api_key)
    provider = ProdamusProvider(settings)

    result = provider.verify_webhook(payload, {})

    assert result.order_id == 101
    assert result.provider_payment_id == "p-1"
    assert result.is_paid is True



def test_prodamus_webhook_accepts_sign_with_unified_key() -> None:
    key = "single_key"
    token = "abc123"
    sign = hashlib.md5(f"{token}{key}".encode("utf-8")).hexdigest()
    payload = (
        '{"order_id": "101", "status": "paid", "payment_id": "p-1", '
        f'"token": "{token}", "sign": "{sign}"'
        "}"
    ).encode("utf-8")
    settings = Settings(prodamus_key=key)
    provider = ProdamusProvider(settings)

    result = provider.verify_webhook(payload, {})

    assert result.order_id == 101
    assert result.provider_payment_id == "p-1"
    assert result.is_paid is True

def test_prodamus_webhook_rejects_invalid_signature() -> None:
    settings = Settings(prodamus_api_key="test_api_key")
    provider = ProdamusProvider(settings)
    payload = (
        '{"order_id": "101", "status": "paid", "payment_id": "p-1", '
        '"token": "abc123", "sign": "invalid"'
        "}"
    ).encode("utf-8")

    try:
        provider.verify_webhook(payload, {})
    except ValueError as exc:
        assert str(exc) == "Invalid Prodamus signature"
    else:
        raise AssertionError("Expected invalid signature error")


def test_prodamus_webhook_accepts_signature_header_name_and_prodamus_secret() -> None:
    secret = "prodamus_secret"
    payload = b'{"order_id":"321","status":"paid","payment_id":"p-9"}'
    sign = hashlib.md5(secret.encode("utf-8") + payload).hexdigest()
    settings = Settings(prodamus_secret=secret)
    provider = ProdamusProvider(settings)

    result = provider.verify_webhook(payload, {"Signature": sign})

    assert result.order_id == 321
    assert result.provider_payment_id == "p-9"
    assert result.is_paid is True


def test_prodamus_webhook_accepts_urlencoded_payload() -> None:
    settings = Settings()
    provider = ProdamusProvider(settings)
    payload = b"order_id=77&status=paid&payment_id=abc%2F123"

    result = provider.verify_webhook(payload, {})

    assert result.order_id == 77
    assert result.provider_payment_id == "abc/123"
    assert result.is_paid is True

def test_prodamus_webhook_accepts_single_key_via_payload_secret_without_signature() -> None:
    key = "single_key"
    payload = (
        '{"order_id": "101", "status": "paid", "payment_id": "p-1", '
        f'"secret": "{key}"'
        "}"
    ).encode("utf-8")
    settings = Settings(prodamus_key=key)
    provider = ProdamusProvider(settings)

    result = provider.verify_webhook(payload, {})

    assert result.order_id == 101
    assert result.provider_payment_id == "p-1"
    assert result.is_paid is True


def test_prodamus_webhook_rejects_wrong_payload_secret_without_signature() -> None:
    payload = b'{"order_id": "101", "status": "paid", "payment_id": "p-1", "secret": "wrong"}'
    settings = Settings(prodamus_key="single_key")
    provider = ProdamusProvider(settings)

    try:
        provider.verify_webhook(payload, {})
    except ValueError as exc:
        assert str(exc) == "Missing Prodamus signature"
    else:
        raise AssertionError("Expected missing signature error")


def test_prodamus_webhook_accepts_nested_order_id_payload() -> None:
    settings = Settings()
    provider = ProdamusProvider(settings)
    payload = b'{"result": {"order": {"id": "445"}, "payment": {"state": "paid", "id": "pm-445"}}}'

    result = provider.verify_webhook(payload, {})

    assert result.order_id == 445
    assert result.provider_payment_id == "pm-445"
    assert result.is_paid is True


def test_prodamus_webhook_rejects_non_numeric_order_id() -> None:
    settings = Settings()
    provider = ProdamusProvider(settings)
    payload = b'{"order_id": "abc", "status": "paid", "payment_id": "p-1"}'

    try:
        provider.verify_webhook(payload, {})
    except ValueError as exc:
        assert str(exc) == "order_id is invalid in Prodamus payload"
    else:
        raise AssertionError("Expected invalid order_id error")
