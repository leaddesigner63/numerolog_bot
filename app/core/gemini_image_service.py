from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.core.config import settings
from app.core.llm_key_store import record_llm_key_usage, resolve_llm_keys


@dataclass(frozen=True)
class GeminiImageResult:
    image_bytes: bytes
    mime_type: str
    model: str


class GeminiImageError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        category: str = "unknown",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.category = category
        self.retry_after = retry_after


class GeminiImageService:
    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)
        timeout_seconds = getattr(settings, "llm_timeout_seconds", 30)
        proxy_url = getattr(settings, "llm_proxy_url", None)
        self._client = self._build_httpx_client(timeout_seconds=timeout_seconds, proxy_url=proxy_url)

    def _build_httpx_client(self, *, timeout_seconds: int, proxy_url: str | None) -> httpx.Client:
        timeout = httpx.Timeout(timeout_seconds)

        if not proxy_url:
            return httpx.Client(timeout=timeout)

        proxies = {"http://": proxy_url, "https://": proxy_url}

        try:
            return httpx.Client(timeout=timeout, proxies=proxies)  # type: ignore[arg-type]
        except TypeError:
            try:
                return httpx.Client(timeout=timeout, proxy=proxy_url)  # type: ignore[call-arg]
            except TypeError:
                self._logger.warning("llm_proxy_not_supported_by_httpx")
                return httpx.Client(timeout=timeout)

    def generate_image(self, prompt: str) -> GeminiImageResult:
        api_keys = resolve_llm_keys(
            provider="gemini",
            primary_key=settings.gemini_api_key,
            extra_keys=settings.gemini_api_keys,
        )
        if not api_keys:
            raise GeminiImageError("Gemini API key is missing", category="missing_api_key")

        model = getattr(settings, "gemini_image_model", None)
        if not model:
            raise GeminiImageError("Gemini image model is missing", category="missing_model")

        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }

        last_error: GeminiImageError | None = None
        for idx, key_item in enumerate(api_keys, start=1):
            headers = {"x-goog-api-key": key_item.key, "Content-Type": "application/json"}
            try:
                response = self._client.post(endpoint, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                record_llm_key_usage(
                    key_item,
                    success=False,
                    status_code=None,
                    error_message=str(exc),
                )
                last_error = GeminiImageError(str(exc), category="network_error")
                self._logger.warning(
                    "gemini_image_request_failed",
                    extra={"key_index": idx, "keys_total": len(api_keys), "error": str(exc)},
                )
                continue

            if response.status_code != 200:
                record_llm_key_usage(
                    key_item,
                    success=False,
                    status_code=response.status_code,
                    error_message=response.text,
                )
                retry_after = self._retry_after_seconds(response.headers.get("Retry-After"))
                category = "bad_status"
                if response.status_code == 429:
                    category = "rate_limited"
                last_error = GeminiImageError(
                    f"Gemini image request failed: {response.text}",
                    status_code=response.status_code,
                    category=category,
                    retry_after=retry_after,
                )
                self._logger.warning(
                    "gemini_image_bad_status",
                    extra={
                        "status_code": response.status_code,
                        "key_index": idx,
                        "keys_total": len(api_keys),
                    },
                )
                if response.status_code in {401, 403, 429, 500, 502, 503, 504} and idx < len(api_keys):
                    if response.status_code == 429:
                        self._sleep_for_rate_limit(retry_after, idx)
                    continue
                raise last_error

            data = response.json()
            image_bytes, mime_type = self._extract_image(data)
            if not image_bytes:
                record_llm_key_usage(
                    key_item,
                    success=False,
                    status_code=response.status_code,
                    error_message="Gemini image response is empty",
                )
                last_error = GeminiImageError("Gemini image response is empty", category="empty_response")
                raise last_error
            record_llm_key_usage(key_item, success=True, status_code=response.status_code)
            return GeminiImageResult(image_bytes=image_bytes, mime_type=mime_type, model=model)

        if last_error:
            raise last_error
        raise GeminiImageError("Gemini image provider failed", category="unknown")

    def _extract_image(self, data: dict[str, Any]) -> tuple[bytes | None, str]:
        candidates = data.get("candidates") or []
        if not candidates:
            return None, "image/png"
        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []
        for part in parts:
            inline = part.get("inlineData") or {}
            image_data = inline.get("data")
            if not image_data:
                continue
            mime_type = inline.get("mimeType") or "image/png"
            try:
                return base64.b64decode(image_data), mime_type
            except (ValueError, TypeError):
                return None, mime_type
        return None, "image/png"

    def _retry_after_seconds(self, value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(float(value), 0.0)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(parsed.timestamp() - time.time(), 0.0)

    def _sleep_for_rate_limit(self, retry_after: float | None, attempt: int) -> None:
        if retry_after is not None:
            delay = retry_after
        else:
            delay = min(2 ** max(attempt - 1, 0), 8)
        if delay > 0:
            time.sleep(delay)


gemini_image_service = GeminiImageService()
