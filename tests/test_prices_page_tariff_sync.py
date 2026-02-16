from pathlib import Path


PRICES_PAGE = Path("web/prices/index.html")


def test_prices_page_loads_tariffs_from_public_api() -> None:
    html = PRICES_PAGE.read_text(encoding="utf-8")

    assert "data-tariff-price=\"T1\"" in html
    assert "data-tariff-price=\"T2\"" in html
    assert "data-tariff-price=\"T3\"" in html
    assert "fetch('/api/public/tariffs'" in html
    assert "updateJsonLdOfferPrices" in html
