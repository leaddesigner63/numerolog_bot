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


def _collect_runtime_state(
    page: Any,
    timeout_ms: int,
    external_state: dict[str, Any] | None = None,
    min_ym_calls: int = 3,
) -> dict[str, Any]:
    elapsed_ms = 0
    step_ms = 200
    last_error = ""
    last_ym_calls: list[Any] = []
    last_redirect_attempts: list[str] = []

    while elapsed_ms <= timeout_ms:
        try:
            state = page.evaluate("() => window.__bridgeSmoke")
        except Exception as exc:  # pragma: no cover - runtime-only browser edge case
            last_error = str(exc)
            state = {}

        ym_calls = state.get("ymCalls", []) if isinstance(state, dict) else []
        redirect_attempts = state.get("redirectAttempts", []) if isinstance(state, dict) else []
        if external_state:
            external_ym_calls = external_state.get("ymCalls", [])
            external_redirect_attempts = external_state.get("redirectAttempts", [])
            if isinstance(external_ym_calls, list):
                ym_calls = external_ym_calls if len(external_ym_calls) >= len(ym_calls) else ym_calls
            if isinstance(external_redirect_attempts, list):
                redirect_attempts = (
                    external_redirect_attempts
                    if len(external_redirect_attempts) >= len(redirect_attempts)
                    else redirect_attempts
                )
        if isinstance(ym_calls, list):
            last_ym_calls = ym_calls
        if isinstance(redirect_attempts, list):
            last_redirect_attempts = redirect_attempts
        enough_ym_calls = isinstance(ym_calls, list) and len(ym_calls) >= min_ym_calls
        redirect_captured = isinstance(redirect_attempts, list) and bool(redirect_attempts)
        if enough_ym_calls and (min_ym_calls > 0 or redirect_captured):
            return {
                "ymCalls": ym_calls,
                "redirectAttempts": redirect_attempts,
                "elapsedMs": elapsed_ms,
                "lastError": last_error,
            }

        page.wait_for_timeout(step_ms)
        elapsed_ms += step_ms

    return {
        "ymCalls": last_ym_calls,
        "redirectAttempts": last_redirect_attempts,
        "elapsedMs": elapsed_ms,
        "lastError": last_error,
    }


def main() -> int:
    base_domain = os.getenv("SOCIAL_SUBDOMAIN_BASE_DOMAIN", "aireadu.ru")
    counter_id = int(os.getenv("SOCIAL_SUBDOMAIN_METRIKA_COUNTER_ID", "106884182"))
    target_event = os.getenv("SOCIAL_SUBDOMAIN_TARGET_EVENT", "bridge_redirect")
    timeout_ms = int(os.getenv("SOCIAL_SUBDOMAIN_RUNTIME_TIMEOUT_MS", "12000"))

    expected_sources = {
        "ig": {"payload": "src=ig&cmp=reels&pl=1", "metrika": True},
        "vk": {"payload": "src=vk&cmp=clips&pl=1", "metrika": True},
        "yt": {"payload": "src=yt&cmp=shorts&pl=1", "metrika": True},
        "ok": {"payload": "src=ok&cmp=video&pl=1", "metrika": False},
    }

    sync_playwright = _load_playwright()
    init_script = """
(() => {
  window.__bridgeSmoke = {
    ymCalls: [],
    redirectAttempts: []
  };

  const locationProto = Object.getPrototypeOf(window.location);
  const originalReplace = locationProto && locationProto.replace;
  if (typeof originalReplace === 'function') {
    locationProto.replace = function(url) {
      window.__bridgeSmoke.redirectAttempts.push(String(url));
      if (typeof window.__bridgeSmokeRecord === 'function') {
        window.__bridgeSmokeRecord('redirect', String(url));
      }
    };
  }

  window.ym = function(...args) {
    window.__bridgeSmoke.ymCalls.push(args);
    if (typeof window.__bridgeSmokeRecord === 'function') {
      window.__bridgeSmokeRecord('ym', args);
    }
    if (args[1] === 'reachGoal') {
      const maybeCallback = args[4];
      if (typeof maybeCallback === 'function') {
        maybeCallback();
      }
    }
  };

})();
"""

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()

            external_smoke_state: dict[str, Any] = {
                "ymCalls": [],
                "redirectAttempts": [],
            }

            def _bridge_smoke_record(_: Any, event_type: str, payload: Any) -> None:
                if event_type == "ym" and isinstance(payload, list):
                    external_smoke_state["ymCalls"].append(payload)
                    return
                if event_type == "redirect" and isinstance(payload, str):
                    external_smoke_state["redirectAttempts"].append(payload)

            context.expose_binding("__bridgeSmokeRecord", _bridge_smoke_record)
            context.add_init_script(init_script)

            for source, source_config in expected_sources.items():
                start_payload = source_config["payload"]
                metrika_enabled = bool(source_config.get("metrika", True))
                url = f"https://{source}.{base_domain}/"
                page = context.new_page()
                request_redirect_attempts: list[str] = []

                def _capture_request(request: Any) -> None:
                    request_url = request.url
                    if isinstance(request_url, str) and request_url.startswith("https://t.me/"):
                        request_redirect_attempts.append(request_url)

                page.on("request", _capture_request)
                external_smoke_state["ymCalls"].clear()
                external_smoke_state["redirectAttempts"].clear()
                print(f"[INFO] Runtime-smoke: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                runtime_state = _collect_runtime_state(
                    page,
                    timeout_ms,
                    external_state=external_smoke_state,
                    min_ym_calls=3 if metrika_enabled else 0,
                )
                ym_calls = runtime_state.get("ymCalls", [])
                redirect_attempts = runtime_state.get("redirectAttempts", [])
                if isinstance(redirect_attempts, list) and request_redirect_attempts:
                    redirect_attempts = [*redirect_attempts, *request_redirect_attempts]

                if metrika_enabled:
                    _assert(
                        len(ym_calls) >= 3,
                        (
                            f"{url}: ожидалось минимум 3 вызова ym, получено {len(ym_calls)}; "
                            f"elapsed_ms={runtime_state.get('elapsedMs')}; "
                            f"last_error={runtime_state.get('lastError', '')}"
                        ),
                    )

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

                    _assert(redirect_attempts, f"{url}: не зафиксирован запрос редиректа в Telegram")
                    redirect_url = redirect_attempts[0]
                    _assert("https://t.me/" in redirect_url, f"{url}: ожидается редирект в Telegram, получено {redirect_url}")
                    _assert("rr=reachGoal_callback" in redirect_url, f"{url}: редирект должен содержать rr=reachGoal_callback")

                    goal_index = ym_calls.index(goal_call)
                    _assert(goal_index >= 2, f"{url}: reachGoal вызван слишком рано, индекс={goal_index}")
                    print(f"[OK] {url}: ym init/hit/reachGoal подтверждены, редирект перехвачен")
                else:
                    _assert(len(ym_calls) == 0, f"{url}: для поддомена без Метрики ym-вызовы не ожидаются")
                    _assert(redirect_attempts, f"{url}: не зафиксирован запрос редиректа в Telegram")
                    redirect_url = redirect_attempts[0]
                    _assert("https://t.me/" in redirect_url, f"{url}: ожидается редирект в Telegram, получено {redirect_url}")
                    _assert("start=src%3Dok%26cmp%3Dvideo%26pl%3D1" in redirect_url, f"{url}: неверный start-параметр редиректа")
                    _assert("rr=fallback_1" in redirect_url, f"{url}: ожидается fallback-редирект для страницы без Метрики")
                    print(f"[OK] {url}: страница без Метрики редиректит по fallback-сценарию")

                page.close()

            browser.close()
    except Exception as exc:
        print(f"[FAIL] Runtime-smoke social subdomains не пройден: {exc}")
        return 1

    print("[OK] Runtime-smoke social subdomains успешно пройден")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
