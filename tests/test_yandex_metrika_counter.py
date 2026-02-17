from pathlib import Path

from app.api.routes.public import _unsubscribe_html_page


def test_all_html_pages_use_standard_yandex_tag_url() -> None:
    web_root = Path("web")
    html_files = sorted(web_root.rglob("*.html"))
    assert html_files

    for html_file in html_files:
        content = html_file.read_text(encoding="utf-8")
        assert "https://mc.yandex.ru/metrika/tag.js\"" in content
        assert "https://mc.yandex.ru/metrika/tag.js?id=" not in content
        assert "ym(106884182, \"init\"" in content


def test_unsubscribe_page_contains_metrika_counter() -> None:
    html = _unsubscribe_html_page(title="t", message="m")
    assert "https://mc.yandex.ru/metrika/tag.js\"" in html
    assert "https://mc.yandex.ru/watch/106884182" in html
    assert 'ym(106884182, "init"' in html
