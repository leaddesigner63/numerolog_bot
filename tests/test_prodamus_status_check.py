from __future__ import annotations

import httpx

from app.core.config import Settings
from app.db.models import Order, OrderStatus, PaymentProvider, Tariff
from app.payments.prodamus import ProdamusProvider


class _DummyClient:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.post_calls: list[dict[str, object]] = []

    def __enter__(self) -> _DummyClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, *, data=None, json=None):
        self.post_calls.append({"url": url, "data": data, "json": json})
        return self._response


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


def test_prodamus_status_check_uses_contract_endpoint_and_form_payload(monkeypatch) -> None:
    settings = Settings(
        prodamus_status_url="https://pay.example/status",
        prodamus_secret="status_secret",
    )
    provider = ProdamusProvider(settings)
    response = httpx.Response(
        200,
        json={"status": "paid", "payment_id": "p-777"},
        request=httpx.Request("POST", "https://pay.example/status"),
    )
    dummy_client = _DummyClient(response)

    def _client_factory(*args, **kwargs):
        return dummy_client

    monkeypatch.setattr("app.payments.prodamus.httpx.Client", _client_factory)

    result = provider.check_payment_status(_order())

    assert result is not None
    assert result.is_paid is True
    assert result.provider_payment_id == "p-777"
    assert dummy_client.post_calls == [
        {
            "url": "https://pay.example/status",
            "data": {"order_id": "777", "secret": "status_secret"},
            "json": None,
        }
    ]


def test_prodamus_status_check_supports_non_paid_statuses_without_crash(monkeypatch) -> None:
    settings = Settings(
        prodamus_status_url="https://pay.example/status",
        prodamus_secret="status_secret",
    )
    provider = ProdamusProvider(settings)

    scenarios = [
        {"status": "pending", "payment_id": "p-pending", "paid": False},
        {"status": "failed", "payment_id": "p-failed", "paid": False},
        {"status": "canceled", "payment_id": "p-cancel", "paid": False},
        {"status": "success", "payment_id": "p-success", "paid": True},
    ]

    for scenario in scenarios:
        response = httpx.Response(
            200,
            json={"status": scenario["status"], "payment_id": scenario["payment_id"]},
            request=httpx.Request("POST", "https://pay.example/status"),
        )
        monkeypatch.setattr("app.payments.prodamus.httpx.Client", lambda *args, **kwargs: _DummyClient(response))

        result = provider.check_payment_status(_order())

        assert result is not None
        assert result.is_paid is scenario["paid"]
        assert result.provider_payment_id == scenario["payment_id"]


def test_prodamus_status_check_parses_nested_and_partial_payloads(monkeypatch) -> None:
    settings = Settings(
        prodamus_status_url="https://pay.example/status",
        prodamus_secret="status_secret",
    )
    provider = ProdamusProvider(settings)

    payloads = [
        ({"result": {"status": "paid", "transaction_id": "tx-1"}}, True, "tx-1"),
        ({"data": {"payment": {"state": "pending", "id": 321}}}, False, "321"),
        ({"payments": [{"status": "failed", "paymentId": "x-9"}]}, False, "x-9"),
        ({}, False, None),
        ({"result": {}}, False, None),
    ]

    for body, expected_paid, expected_payment_id in payloads:
        response = httpx.Response(
            200,
            json=body,
            request=httpx.Request("POST", "https://pay.example/status"),
        )
        monkeypatch.setattr("app.payments.prodamus.httpx.Client", lambda *args, **kwargs: _DummyClient(response))

        result = provider.check_payment_status(_order())

        assert result is not None
        assert result.is_paid is expected_paid
        assert result.provider_payment_id == expected_payment_id


def test_prodamus_status_check_uses_form_url_when_status_url_missing(monkeypatch) -> None:
    settings = Settings(
        prodamus_form_url="https://pay.example/form",
        prodamus_secret="status_secret",
    )
    provider = ProdamusProvider(settings)
    response = httpx.Response(
        200,
        json={"status": "paid", "payment_id": "p-778"},
        request=httpx.Request("POST", "https://pay.example/form"),
    )
    dummy_client = _DummyClient(response)

    monkeypatch.setattr(
        "app.payments.prodamus.httpx.Client", lambda *args, **kwargs: dummy_client
    )

    result = provider.check_payment_status(_order())

    assert result is not None
    assert result.is_paid is True
    assert result.provider_payment_id == "p-778"
    assert dummy_client.post_calls == [
        {
            "url": "https://pay.example/form",
            "data": {"order_id": "777", "secret": "status_secret"},
            "json": None,
        }
    ]


def test_prodamus_status_check_handles_non_utf8_response_body(monkeypatch) -> None:
    settings = Settings(
        prodamus_status_url="https://pay.example/status",
        prodamus_secret="status_secret",
    )
    provider = ProdamusProvider(settings)

    response = httpx.Response(
        200,
        content=b'{"status":"paid"}\xce',
        request=httpx.Request("POST", "https://pay.example/status"),
    )
    monkeypatch.setattr("app.payments.prodamus.httpx.Client", lambda *args, **kwargs: _DummyClient(response))

    result = provider.check_payment_status(_order())

    assert result is not None
    assert result.is_paid is False
    assert result.provider_payment_id is None
