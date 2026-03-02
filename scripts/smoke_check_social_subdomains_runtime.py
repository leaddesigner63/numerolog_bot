#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from typing import Any


def _load_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        print(f"[FAIL] Не удалось импортировать playwright: {exc}")
        print("[HINT] Установите зависимости: pip install playwright && python -m playwright install chromium")
        sys.exit(1)

    return sync_playwright


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    base_domain = os.getenv("SOCIAL_SUBDOMAIN_BASE_DOMAIN", "aireadu.ru")
    counter_id = int(os.getenv("SOCIAL_SUBDOMAIN_METRIKA_COUNTER_ID", "106884182"))
    target_event = os.getenv("SOCIAL_SUBDOMAIN_TARGET_EVENT", "bridge_redirect")
    timeout_ms = int(os.getenv("SOCIAL_SUBDOMAIN_RUNTIME_TIMEOUT_MS", "12000"))

    expected_sources = {
        "ig": "src=ig&cmp=reels&pl=1",
        "vk": "src=vk&cmp=clips&pl=1",
        "yt": "src=yt&cmp=shorts&pl=1",
    }

    sync_playwright = _load_playwright()
    init_script = """
(() => {
  window.__bridgeSmoke = {
    ymCalls: [],
    redirects: []
  };

  window.ym = function(...args) {
    window.__bridgeSmoke.ymCalls.push(args);
    if (args[1] === 'reachGoal') {
      const maybeCallback = args[4];
      if (typeof maybeCallback === 'function') {
        maybeCallback();
      }
    }
  };

  const originalReplace = window.location.replace.bind(window.location);
  window.location.replace = function(url) {
    window.__bridgeSmoke.redirects.push(url);
    return undefined;
  };

  window.__bridgeSmoke.originalReplaceType = typeof originalReplace;
})();
"""

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            context.add_init_script(init_script)

            for source, start_payload in expected_sources.items():
                url = f"https://{source}.{base_domain}/"
                page = context.new_page()
                print(f"[INFO] Runtime-smoke: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(300)

                state = page.evaluate("() => window.__bridgeSmoke")
                ym_calls = state.get("ymCalls", [])
                redirects = state.get("redirects", [])

                _assert(len(ym_calls) >= 3, f"{url}: ожидалось минимум 3 вызова ym, получено {len(ym_calls)}")

                init_call = next((call for call in ym_calls if len(call) > 1 and call[1] == "init"), None)
                hit_call = next((call for call in ym_calls if len(call) > 1 and call[1] == "hit"), None)
                goal_call = next((call for call in ym_calls if len(call) > 1 and call[1] == "reachGoal"), None)

                _assert(init_call is not None, f"{url}: не найден вызов ym(..., 'init', ...)")
                _assert(hit_call is not None, f"{url}: не найден вызов ym(..., 'hit', ...)")
                _assert(goal_call is not None, f"{url}: не найден вызов ym(..., 'reachGoal', ...)")

                _assert(init_call[0] == counter_id, f"{url}: ym init counter_id {init_call[0]} != {counter_id}")
                _assert(hit_call[0] == counter_id, f"{url}: ym hit counter_id {hit_call[0]} != {counter_id}")
                _assert(goal_call[0] == counter_id, f"{url}: ym reachGoal counter_id {goal_call[0]} != {counter_id}")
                _assert(goal_call[2] == target_event, f"{url}: reachGoal event {goal_call[2]} != {target_event}")

                params = goal_call[3] if len(goal_call) > 3 and isinstance(goal_call[3], dict) else {}
                _assert(params.get("source") == source, f"{url}: reachGoal.source {params.get('source')} != {source}")
                _assert(
                    params.get("start_payload") == start_payload,
                    f"{url}: reachGoal.start_payload {params.get('start_payload')} != {start_payload}",
                )

                _assert(redirects, f"{url}: не зафиксирован вызов window.location.replace")
                redirect_url = redirects[0]
                _assert("https://t.me/" in redirect_url, f"{url}: ожидается редирект в Telegram, получено {redirect_url}")
                _assert("rr=reachGoal_callback" in redirect_url, f"{url}: редирект должен содержать rr=reachGoal_callback")

                goal_index = ym_calls.index(goal_call)
                _assert(goal_index >= 2, f"{url}: reachGoal вызван слишком рано, индекс={goal_index}")
                print(f"[OK] {url}: ym init/hit/reachGoal подтверждены, редирект перехвачен")

                page.close()

            browser.close()
    except Exception as exc:
        print(f"[FAIL] Runtime-smoke social subdomains не пройден: {exc}")
        return 1

    print("[OK] Runtime-smoke social subdomains успешно пройден")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
