from app.bot.handlers.screens import _tariff_prices
from app.bot.screens import _format_price
from app.core.config import Settings
from app.db.models import Tariff


def test_settings_tariff_prices_from_env_fields() -> None:
    settings = Settings(
        tariff_t0_price_rub=10,
        tariff_t1_price_rub=100,
        tariff_t2_price_rub=200,
        tariff_t3_price_rub=300,
    )

    assert settings.tariff_prices_rub == {"T0": 10, "T1": 100, "T2": 200, "T3": 300}


def test_format_price_uses_settings_tariff_values(monkeypatch) -> None:
    monkeypatch.setattr("app.bot.screens.settings.tariff_t1_price_rub", 777)
    monkeypatch.setattr("app.bot.screens.settings.tariff_t2_price_rub", 1888)
    monkeypatch.setattr("app.bot.screens.settings.tariff_t3_price_rub", 2999)

    assert _format_price({}, "T1") == "777 RUB"
    assert _format_price({}, "T2") == "1888 RUB"
    assert _format_price({}, "T3") == "2999 RUB"


def test_create_order_price_uses_settings_tariff_values(monkeypatch) -> None:
    monkeypatch.setattr("app.bot.handlers.screens.settings.tariff_t1_price_rub", 1500)
    monkeypatch.setattr("app.bot.handlers.screens.settings.tariff_t2_price_rub", 2500)
    monkeypatch.setattr("app.bot.handlers.screens.settings.tariff_t3_price_rub", 3500)

    prices = _tariff_prices()

    assert prices[Tariff.T1] == 1500
    assert prices[Tariff.T2] == 2500
    assert prices[Tariff.T3] == 3500
