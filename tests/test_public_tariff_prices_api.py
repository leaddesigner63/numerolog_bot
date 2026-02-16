from fastapi.testclient import TestClient

from app.main import create_app


def test_public_tariffs_returns_prices_from_settings(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.public.settings.tariff_t0_price_rub", 10)
    monkeypatch.setattr("app.api.routes.public.settings.tariff_t1_price_rub", 110)
    monkeypatch.setattr("app.api.routes.public.settings.tariff_t2_price_rub", 220)
    monkeypatch.setattr("app.api.routes.public.settings.tariff_t3_price_rub", 330)

    app = create_app()
    client = TestClient(app)

    response = client.get("/api/public/tariffs")

    assert response.status_code == 200
    assert response.json() == {
        "currency": "RUB",
        "tariffs": {
            "T0": 10,
            "T1": 110,
            "T2": 220,
            "T3": 330,
        },
    }
