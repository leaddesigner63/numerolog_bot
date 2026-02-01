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
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.fallback = fallback


class LLMUnavailableError(RuntimeError):
    pass


class LLMRouter:
    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)
        self._fallback_statuses = {401, 403, 429}

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
                },
            )
        raise LLMUnavailableError("Both Gemini and OpenAI providers are unavailable")

    def _call_gemini(self, facts_pack: dict[str, Any], system_prompt: str) -> LLMResponse:
        if not settings.gemini_api_key:
            raise LLMProviderError(
                "Gemini API key is missing",
                retryable=False,
                fallback=True,
            )

        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent"
        )
        params = {"key": settings.gemini_api_key}
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

        data = self._post_with_retries(
            endpoint,
            params=params,
            json_payload=payload,
            max_retries=2,
            retry_statuses={500, 502, 503, 504},
            fallback_statuses=self._fallback_statuses,
        )

        text = self._extract_gemini_text(data)
        if not text:
            raise LLMProviderError("Gemini response is empty", retryable=False)
        return LLMResponse(text=text, provider="gemini", model=settings.gemini_model)

    def _call_openai(self, facts_pack: dict[str, Any], system_prompt: str) -> LLMResponse:
        if not settings.openai_api_key:
            raise LLMProviderError("OpenAI API key is missing", retryable=False)

        endpoint = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
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
            raise LLMProviderError("OpenAI response is empty", retryable=False)
        return LLMResponse(text=text, provider="openai", model=settings.openai_model)

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
                ) from exc
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in retry_statuses and attempts < max_retries:
                    attempts += 1
                    self._sleep_backoff(attempts)
                    continue
                retryable = status in retry_statuses or status >= 500
                fallback = status in fallback_statuses or status >= 500
                if fallback:
                    raise LLMProviderError(
                        f"LLM provider returned status {status}",
                        status_code=status,
                        retryable=retryable,
                        fallback=True,
                    ) from exc
                raise LLMProviderError(
                    f"LLM provider returned status {status}",
                    status_code=status,
                    retryable=False,
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
                ) from exc

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        time.sleep(0.2 * attempt)

    @staticmethod
    def _build_prompt(system_prompt: str, facts_pack: dict[str, Any]) -> str:
        payload = json.dumps(facts_pack, ensure_ascii=False, indent=2)
        return f"{system_prompt}\n\nДанные (facts-pack):\n{payload}"

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
