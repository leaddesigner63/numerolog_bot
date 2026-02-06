from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.llm_key_store import record_llm_key_usage, resolve_llm_keys


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str


class LLMProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        fallback: bool = False,
        category: str = "unknown",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.fallback = fallback
        self.category = category
        self.retry_after = retry_after


class LLMUnavailableError(RuntimeError):
    pass


class LLMRouter:
    """
    Требования:
    - Ключи подхватываются из .env через settings.*.
    - Ключи задаются одной строкой через запятую (порядок важен).
    - Основной провайдер: Gemini. Резервный: OpenAI.
    - При неудаче перебираем ключи по порядку.
    - Прокси используется СТРОГО для LLM (Gemini/OpenAI), если задан LLM_PROXY_URL.
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

        # По каким статусам делаем retry на ТОМ ЖЕ ключе
        self._retry_statuses = {429, 500, 502, 503, 504}

        timeout_seconds = getattr(settings, "llm_timeout_seconds", 30)

        # Прокси применяется ТОЛЬКО тут (в LLMRouter), т.е. только LLM-трафик уйдет через прокси.
        proxy_url = getattr(settings, "llm_proxy_url", None)

        self._client = self._build_httpx_client(timeout_seconds=timeout_seconds, proxy_url=proxy_url)
        self._rate_limit_until: dict[str, float] = {}

    def _build_httpx_client(self, *, timeout_seconds: int, proxy_url: str | None) -> httpx.Client:
        timeout = httpx.Timeout(timeout_seconds)

        if not proxy_url:
            return httpx.Client(timeout=timeout)

        # Совместимость с разными версиями httpx:
        # - часть версий поддерживает proxies={...}
        # - часть версий поддерживает proxy="..."
        proxies = {"http://": proxy_url, "https://": proxy_url}

        try:
            return httpx.Client(timeout=timeout, proxies=proxies)  # type: ignore[arg-type]
        except TypeError:
            try:
                return httpx.Client(timeout=timeout, proxy=proxy_url)  # type: ignore[call-arg]
            except TypeError:
                # Если вдруг версия совсем древняя/нестандартная — работаем без прокси, но логируем.
                self._logger.warning("llm_proxy_not_supported_by_httpx")
                return httpx.Client(timeout=timeout)

    def generate(self, facts_pack: dict[str, Any], system_prompt: str) -> LLMResponse:
        # 1) Gemini (primary)
        try:
            return self._call_gemini(facts_pack, system_prompt)
        except LLMProviderError as exc:
            self._logger.warning(
                "gemini_failed",
                extra={
                    "status_code": exc.status_code,
                    "retryable": exc.retryable,
                    "fallback": exc.fallback,
                    "category": exc.category,
                },
            )
            if not exc.fallback:
                raise LLMUnavailableError("Gemini provider failed without fallback") from exc

        self._logger.warning(
            "llm_fallback",
            extra={"provider": "gemini", "fallback_provider": "openai"},
        )

        # 2) OpenAI (fallback)
        try:
            return self._call_openai(facts_pack, system_prompt)
        except LLMProviderError as exc:
            self._logger.warning(
                "openai_failed",
                extra={
                    "status_code": exc.status_code,
                    "retryable": exc.retryable,
                    "fallback": exc.fallback,
                    "category": exc.category,
                },
            )
            raise LLMUnavailableError("Both Gemini and OpenAI providers are unavailable") from exc

    def _call_gemini(self, facts_pack: dict[str, Any], system_prompt: str) -> LLMResponse:
        api_keys = resolve_llm_keys(
            provider="gemini",
            primary_key=settings.gemini_api_key,
            extra_keys=settings.gemini_api_keys,
        )
        if not api_keys:
            raise LLMProviderError(
                "Gemini API key is missing",
                retryable=False,
                fallback=True,
                category="missing_api_key",
            )

        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": self._build_prompt(system_prompt, facts_pack)}],
                }
            ]
        }

        # Если Gemini отвечает этими статусами — разумно фолбэкнуть на OpenAI
        gemini_fallback_statuses = {400, 401, 403, 404, 429, 500, 502, 503, 504}

        last_error: LLMProviderError | None = None
        for idx, key_item in enumerate(api_keys, start=1):
            if self._is_rate_limited(key_item.key):
                self._logger.info(
                    "gemini_key_rate_limited_skip",
                    extra={"key_index": idx, "keys_total": len(api_keys)},
                )
                if idx < len(api_keys):
                    continue
                raise LLMProviderError(
                    "Gemini key is rate limited",
                    status_code=429,
                    retryable=True,
                    fallback=True,
                    category="rate_limited",
                )
            headers = {
                # НЕ передаём ключ в URL, чтобы он не попадал в httpx-логи
                "x-goog-api-key": key_item.key,
                "Content-Type": "application/json",
            }

            try:
                data = self._post_json(
                    endpoint,
                    headers=headers,
                    json_payload=payload,
                    max_retries=2,
                    fallback_statuses=gemini_fallback_statuses,
                )
                text = self._extract_gemini_text(data)
                if not text:
                    raise LLMProviderError(
                        "Gemini response is empty",
                        retryable=False,
                        fallback=True,
                        category="empty_response",
                    )
                record_llm_key_usage(key_item, success=True, status_code=200)
                return LLMResponse(text=text, provider="gemini", model=settings.gemini_model)

            except LLMProviderError as exc:
                last_error = exc
                self._mark_rate_limit(key_item.key, exc)
                record_llm_key_usage(
                    key_item,
                    success=False,
                    status_code=exc.status_code,
                    error_message=str(exc),
                )
                self._logger.warning(
                    "gemini_key_failed",
                    extra={
                        "status_code": exc.status_code,
                        "retryable": exc.retryable,
                        "fallback": exc.fallback,
                        "category": exc.category,
                        "key_index": idx,
                        "keys_total": len(api_keys),
                    },
                )

                # Требование: fallback допускается только после исчерпания всех ключей основного провайдера.
                # Поэтому при любой ошибке пытаемся следующий ключ, если он есть.
                if idx < len(api_keys):
                    continue

                raise

        if last_error:
            raise last_error
        raise LLMProviderError(
            "Gemini provider failed",
            retryable=False,
            fallback=True,
            category="unknown",
        )

    def _call_openai(self, facts_pack: dict[str, Any], system_prompt: str) -> LLMResponse:
        api_keys = resolve_llm_keys(
            provider="openai",
            primary_key=settings.openai_api_key,
            extra_keys=settings.openai_api_keys,
        )
        if not api_keys:
            raise LLMProviderError(
                "OpenAI API key is missing",
                retryable=False,
                fallback=False,
                category="missing_api_key",
            )

        endpoint = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": settings.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(facts_pack, ensure_ascii=False)},
            ],
        }

        openai_fallback_statuses = {401, 403, 404, 429, 500, 502, 503, 504}

        last_error: LLMProviderError | None = None
        for idx, key_item in enumerate(api_keys, start=1):
            if self._is_rate_limited(key_item.key):
                self._logger.info(
                    "openai_key_rate_limited_skip",
                    extra={"key_index": idx, "keys_total": len(api_keys)},
                )
                if idx < len(api_keys):
                    continue
                raise LLMProviderError(
                    "OpenAI key is rate limited",
                    status_code=429,
                    retryable=True,
                    fallback=False,
                    category="rate_limited",
                )
            headers = {
                "Authorization": f"Bearer {key_item.key}",
                "Content-Type": "application/json",
            }

            try:
                data = self._post_json(
                    endpoint,
                    headers=headers,
                    json_payload=payload,
                    max_retries=2,
                    fallback_statuses=openai_fallback_statuses,
                )
                text = self._extract_openai_text(data)
                if not text:
                    raise LLMProviderError(
                        "OpenAI response is empty",
                        retryable=False,
                        fallback=False,
                        category="empty_response",
                    )
                record_llm_key_usage(key_item, success=True, status_code=200)
                return LLMResponse(text=text, provider="openai", model=settings.openai_model)

            except LLMProviderError as exc:
                last_error = exc
                self._mark_rate_limit(key_item.key, exc)
                record_llm_key_usage(
                    key_item,
                    success=False,
                    status_code=exc.status_code,
                    error_message=str(exc),
                )
                self._logger.warning(
                    "openai_key_failed",
                    extra={
                        "status_code": exc.status_code,
                        "retryable": exc.retryable,
                        "fallback": exc.fallback,
                        "category": exc.category,
                        "key_index": idx,
                        "keys_total": len(api_keys),
                    },
                )

                # Для fallback-провайдера также перебираем все ключи до финального отказа.
                if idx < len(api_keys):
                    continue
                raise

        if last_error:
            raise last_error
        raise LLMProviderError(
            "OpenAI provider failed",
            retryable=False,
            fallback=False,
            category="unknown",
        )

    def _post_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None,
        json_payload: dict[str, Any],
        max_retries: int,
        fallback_statuses: set[int],
    ) -> dict[str, Any]:
        attempts = 0

        while True:
            try:
                resp = self._client.post(url, json=json_payload, headers=headers)
            except httpx.TimeoutException as exc:
                attempts += 1
                if attempts <= max_retries:
                    self._sleep_backoff(attempts)
                    continue
                raise LLMProviderError(
                    "LLM request timed out",
                    retryable=True,
                    fallback=True,
                    category="timeout",
                ) from exc
            except httpx.RequestError as exc:
                attempts += 1
                if attempts <= max_retries:
                    self._sleep_backoff(attempts)
                    continue
                raise LLMProviderError(
                    "LLM request failed",
                    retryable=True,
                    fallback=True,
                    category="request_error",
                ) from exc

            status = resp.status_code

            if 200 <= status < 300:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise LLMProviderError(
                        "LLM provider returned non-JSON response",
                        status_code=status,
                        retryable=False,
                        fallback=True,
                        category="bad_response",
                    ) from exc

            if status in self._retry_statuses and attempts < max_retries:
                attempts += 1
                self._sleep_backoff(attempts, retry_after=self._retry_after_seconds(resp))
                continue

            retry_after = self._retry_after_seconds(resp)
            raise LLMProviderError(
                self._format_error_message(status, resp),
                status_code=status,
                retryable=status in self._retry_statuses or status >= 500,
                fallback=status in fallback_statuses or status >= 500,
                category=self._status_category(status),
                retry_after=retry_after,
            )

    @staticmethod
    def _retry_after_seconds(resp: httpx.Response) -> float | None:
        val = resp.headers.get("retry-after")
        if not val:
            return None
        try:
            return float(val.strip())
        except ValueError:
            return None

    @staticmethod
    def _sleep_backoff(attempt: int, *, retry_after: float | None = None) -> None:
        if retry_after is not None:
            time.sleep(max(0.2, retry_after))
            return
        time.sleep(0.3 * attempt)

    @staticmethod
    def _build_prompt(system_prompt: str, facts_pack: dict[str, Any]) -> str:
        payload = json.dumps(facts_pack, ensure_ascii=False, indent=2)
        return f"{system_prompt}\n\nДанные (facts-pack):\n{payload}"

    @staticmethod
    def _status_category(status: int) -> str:
        if status == 400:
            return "invalid_request"
        if status in {401, 403}:
            return "auth_error"
        if status == 404:
            return "not_found"
        if status == 429:
            return "rate_limited"
        if status >= 500:
            return "server_error"
        return "http_error"

    @staticmethod
    def _format_error_message(status: int, resp: httpx.Response) -> str:
        try:
            data = resp.json()
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    msg = err.get("message")
                    code = err.get("code")
                    typ = err.get("type") or err.get("status")
                    parts: list[str] = []
                    if msg:
                        parts.append(str(msg))
                    if typ:
                        parts.append(f"type={typ}")
                    if code:
                        parts.append(f"code={code}")
                    if parts:
                        return f"LLM provider returned status {status}: " + " | ".join(parts)
        except Exception:
            pass

        raw = (resp.text or "").replace("\n", " ").strip()
        if raw:
            return f"LLM provider returned status {status}: {raw[:200]}"
        return f"LLM provider returned status {status}"

    def _is_rate_limited(self, key: str) -> bool:
        until = self._rate_limit_until.get(key)
        if not until:
            return False
        if time.time() >= until:
            self._rate_limit_until.pop(key, None)
            return False
        return True

    def _mark_rate_limit(self, key: str, exc: LLMProviderError) -> None:
        if exc.status_code != 429:
            return
        retry_after = exc.retry_after or 10.0
        self._rate_limit_until[key] = time.time() + max(1.0, retry_after)

    @staticmethod
    def _extract_gemini_text(data: dict[str, Any]) -> str | None:
        candidates = data.get("candidates") or []
        if not candidates:
            return None
        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []
        if not parts:
            return None
        return parts[0].get("text")

    @staticmethod
    def _extract_openai_text(data: dict[str, Any]) -> str | None:
        choices = data.get("choices") or []
        if not choices:
            return None
        message = choices[0].get("message") or {}
        return message.get("content")

llm_router = LLMRouter()
