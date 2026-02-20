from pathlib import Path


PRICES_PAGE = Path("web/prices/index.html")


def test_prices_page_loads_tariffs_from_public_api() -> None:
    html = PRICES_PAGE.read_text(encoding="utf-8")

    assert 'data-tariff-price="T0"' in html
    assert 'data-tariff-price="T1"' in html
    assert 'data-tariff-price="T2"' in html
    assert 'data-tariff-price="T3"' in html
    assert "fetch('/api/public/tariffs'" in html
    assert "updateJsonLdOfferPrices" in html


def test_prices_page_tariff_cta_have_deeplink_and_tracking_attributes() -> None:
    html = PRICES_PAGE.read_text(encoding="utf-8")

    assert 'data-telegram-cta data-tariff="T0" data-placement="tariff_t0"' in html
    assert 'data-telegram-cta data-tariff="T1" data-placement="tariff_t1"' in html
    assert 'data-telegram-cta data-tariff="T2" data-placement="tariff_t2"' in html
    assert 'data-telegram-cta data-tariff="T3" data-placement="tariff_t3"' in html
    assert "Рекомендуем" in html
