from pathlib import Path


WEB_ROOT = Path("web")
EXPECTED_FALLBACK = "https://t.me/AIreadUbot?start=src_site_cmp_seo_pl_na"


def test_landing_links_use_new_fallback_payload() -> None:
    html_files = sorted(WEB_ROOT.rglob("*.html"))
    landing_files = [path for path in html_files if "site_seo_all" in path.read_text(encoding="utf-8")]
    assert landing_files == []

    files_with_fallback = [
        path
        for path in html_files
        if EXPECTED_FALLBACK in path.read_text(encoding="utf-8")
    ]
    assert files_with_fallback


def test_prices_tariff_cards_have_expected_placements() -> None:
    prices_html = (WEB_ROOT / "prices" / "index.html").read_text(encoding="utf-8")
    for placement in ("tariff_t0", "tariff_t1", "tariff_t2", "tariff_t3"):
        assert f'data-placement="{placement}"' in prices_html
