from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings


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
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.fallback = fallback
        self.category = category


class LLMUnavailableError(RuntimeError):
    pass


class LLMRouter:
    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)
        self._fallback_statuses = {401, 403, 429}
        self._gemini_fallback_statuses = {400, 401, 403, 404, 429}

    def generate(self, facts_pack: dict[str, Any], system_prompt: str) -> LLMResponse:
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
            if exc.fallback:
                self._logger.warning(
                    "llm_fallback",
                    extra={
                        "provider": "gemini",
                        "fallback_provider": "openai",
                        "category": exc.category,
                        "status_code": exc.status_code,
                    },
                )
            if not exc.fallback:
                raise LLMUnavailableError("Gemini provider failed without fallback") from exc

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
        raise LLMUnavailableError("Both Gemini and OpenAI providers are unavailable")

    def _call_gemini(self, facts_pack: dict[str, Any], system_prompt: str) -> LLMResponse:
        api_keys = self._collect_api_keys(settings.gemini_api_key, settings.gemini_api_keys)
        if not api_keys:
            self._logger.warning("gemini_api_key_missing")
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
                    "parts": [
                        {
                            "text": self._build_prompt(system_prompt, facts_pack),
                        }
                    ],
                }
            ]
        }

        last_error: LLMProviderError | None = None
        for index, api_key in enumerate(api_keys, start=1):
            params = {"key": api_key}
            try:
                data = self._post_with_retries(
                    endpoint,
                    params=params,
                    json_payload=payload,
                    max_retries=2,
                    retry_statuses={500, 502, 503, 504},
                    fallback_statuses=self._gemini_fallback_statuses,
                )
                text = self._extract_gemini_text(data)
                if not text:
                    raise LLMProviderError(
                        "Gemini response is empty",
                        retryable=False,
                        category="empty_response",
                    )
                return LLMResponse(text=text, provider="gemini", model=settings.gemini_model)
            except LLMProviderError as exc:
                last_error = exc
                self._logger.warning(
                    "gemini_key_failed",
                    extra={
                        "status_code": exc.status_code,
                        "retryable": exc.retryable,
                        "fallback": exc.fallback,
                        "category": exc.category,
                        "key_index": index,
                        "keys_total": len(api_keys),
                    },
                )
                if exc.status_code in {400, 404}:
                    raise
                if not exc.fallback or index == len(api_keys):
                    raise
                continue

        if last_error:
            raise last_error
        raise LLMProviderError(
            "Gemini provider failed without available keys",
            retryable=False,
            fallback=True,
            category="missing_api_key",
        )

    def _call_openai(self, facts_pack: dict[str, Any], system_prompt: str) -> LLMResponse:
        api_keys = self._collect_api_keys(settings.openai_api_key, settings.openai_api_keys)
        if not api_keys:
            self._logger.warning("openai_api_key_missing")
            raise LLMProviderError(
                "OpenAI API key is missing",
                retryable=False,
                category="missing_api_key",
            )

        endpoint = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": settings.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(facts_pack, ensure_ascii=False),
                },
            ],
        }

        last_error: LLMProviderError | None = None
        for index, api_key in enumerate(api_keys, start=1):
            headers = {"Authorization": f"Bearer {api_key}"}
            try:
                data = self._post_with_retries(
                    endpoint,
                    headers=headers,
                    json_payload=payload,
                    max_retries=1,
                    retry_statuses={500, 502, 503, 504},
                    fallback_statuses=self._fallback_statuses,
                )
                text = self._extract_openai_text(data)
                if not text:
                    raise LLMProviderError(
                        "OpenAI response is empty",
                        retryable=False,
                        category="empty_response",
                    )
                return LLMResponse(text=text, provider="openai", model=settings.openai_model)
            except LLMProviderError as exc:
                last_error = exc
                self._logger.warning(
                    "openai_key_failed",
                    extra={
                        "status_code": exc.status_code,
                        "retryable": exc.retryable,
                        "fallback": exc.fallback,
                        "category": exc.category,
                        "key_index": index,
                        "keys_total": len(api_keys),
                    },
                )
                if not exc.fallback or index == len(api_keys):
                    raise
                continue

        if last_error:
            raise last_error
        raise LLMProviderError(
            "OpenAI provider failed without available keys",
            retryable=False,
            fallback=True,
            category="missing_api_key",
        )

    def _post_with_retries(
        self,
        url: str,
        *,
        json_payload: dict[str, Any],
        max_retries: int,
        retry_statuses: set[int],
        fallback_statuses: set[int],
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        attempts = 0
        timeout = httpx.Timeout(settings.llm_timeout_seconds)

        while True:
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(
                        url,
                        json=json_payload,
                        headers=headers,
                        params=params,
                    )
                    response.raise_for_status()
                    return response.json()
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
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in retry_statuses and attempts < max_retries:
                    attempts += 1
                    self._sleep_backoff(attempts)
                    continue
                retryable = status in retry_statuses or status >= 500
                fallback = status in fallback_statuses or status >= 500
                category = self._status_category(status)
                if fallback:
                    raise LLMProviderError(
                        f"LLM provider returned status {status}",
                        status_code=status,
                        retryable=retryable,
                        fallback=True,
                        category=category,
                    ) from exc
                raise LLMProviderError(
                    f"LLM provider returned status {status}",
                    status_code=status,
                    retryable=False,
                    category=category,
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

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        time.sleep(0.2 * attempt)

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

    @staticmethod
    def _collect_api_keys(primary_key: str | None, extra_keys: str | None) -> list[str]:
        keys: list[str] = []
        for raw in (primary_key, extra_keys):
            if not raw:
                continue
            for part in raw.replace(";", ",").split(","):
                key = part.strip()
                if key:
                    keys.append(key)
        seen: set[str] = set()
        unique_keys: list[str] = []
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            unique_keys.append(key)
        return unique_keys


llm_router = LLMRouter()
