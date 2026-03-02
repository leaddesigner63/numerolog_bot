from __future__ import annotations

import re
from pathlib import Path


BRIDGE_PAGES = {
    "ig": "ig_reels_1",
    "vk": "vk_clips_1",
    "yt": "yt_shorts_1",
}


def _read_bridge_page(source: str) -> str:
    return Path(f"web/{source}/index.html").read_text(encoding="utf-8")


def test_bridge_pages_do_not_use_instant_meta_refresh() -> None:
    instant_meta_refresh_pattern = re.compile(
        r"<meta[^>]+http-equiv=[\"']refresh[\"'][^>]+content=[\"']\s*0\s*;",
        re.IGNORECASE,
    )

    for source in BRIDGE_PAGES:
        html = _read_bridge_page(source)
        assert instant_meta_refresh_pattern.search(html) is None


def test_bridge_pages_have_redirect_function_metrika_calls_and_fallback_timer() -> None:
    for source in BRIDGE_PAGES:
        html = _read_bridge_page(source)

        assert "function redirectToBot()" in html
        assert 'ym(106884182, "hit"' in html or 'ym(106884182, "reachGoal"' in html
        assert "setTimeout(redirectToBot," in html or "setTimeout(function()" in html


def test_bridge_pages_have_unique_source_and_start_payload() -> None:
    seen_sources: set[str] = set()
    seen_start_payloads: set[str] = set()

    for source, expected_payload in BRIDGE_PAGES.items():
        html = _read_bridge_page(source)

        source_match = re.search(r"var source = '([^']+)';", html)
        payload_match = re.search(r"var startPayload = '([^']+)';", html)

        assert source_match is not None
        assert payload_match is not None

        source_value = source_match.group(1)
        payload_value = payload_match.group(1)

        assert source_value == source
        assert payload_value == expected_payload

        assert source_value not in seen_sources
        assert payload_value not in seen_start_payloads

        seen_sources.add(source_value)
        seen_start_payloads.add(payload_value)
