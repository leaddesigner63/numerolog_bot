fr:contentReference[oaicite:2]{index=2}annotations

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

        # ВАЖНО:
        # - 429 НЕ считаем "плохим ключом" (иначе начинается перебор ключей и ловим 401 на следующем)
        # - 401/403/404 считаем фатальными/ключевыми и допускаем перебор ключей
        self._fallback_statuses = {401, 403, 404}
        # Gemini: 404 = модель не найдена / выключена; 429 = rate limit; 401/403 = ключ/доступ
        self._gemini_fallback_statuses = {400, 401, 403, 404, 429}

        # Ретраи по статусам (сюда включаем 429)
        self._retry_statuses_common = {429, 500, 502, 503, 504}

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
                    "error": str(exc),
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
                    "error": str(exc),
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
            # НЕ передаём ключ в URL (чтобы httpx-логи не светили ?key=...).
            # Gemini API официально поддерживает заголовок x-goog-api-key.
            headers = {"x-goog-api-key": api_key}

            try:
                data = self._post_with_retries(
                    endpoint,
                    headers=headers,
                    json_payload=payload,
                    max_retries=2,
                    retry_statuses=self._retry_statuses_common,
                    fallback_statuses=self._gemini_fallback_statuses,
                )
                text = self._extract_gemini_text(data)
                if not text:
                    raise LLMProviderError(
                        "Gemini response is empty",
                        retryable=False,
                        fallback=True,
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
                        "error": str(exc),
                        "key_index": index,
                        "keys_total": len(api_keys),
                    },
                )

                # 400/404 обычно не лечатся сменой ключа (неверный запрос / модели нет)
                if exc.status_code in {400, 404}:
                    raise

                # Перебираем ключи только при auth-ошибках (401/403).
                if exc.status_code in {401, 403} and index < len(api_keys):
                    continue

                # На 429 и прочее — пусть сработает fallback на OpenAI (через generate()).
                raise

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
                fallback=True,
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

        last_error: LLMProviderError | None = None
        for index, api_key in enumerate(api_keys, start=1):
            headers = {"Authorization": f"Bearer {api_key}"}

            try:
                data = self._post_with_retries(
                    endpoint,
                    headers=headers,
                    json_payload=payload,
                    max_retries=2,
                    retry_statuses=self._retry_statuses_common,
                    fallback_statuses=self._fallback_statuses,
                )
                text = self._extract_openai_text(data)
                if not text:
                    raise LLMProviderError(
                        "OpenAI response is empty",
                        retryable=False,
                        fallback=True,
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
                        "error": str(exc),
                        "key_index": index,
                        "keys_total": len(api_keys),
                    },
                )

                # Перебор ключей делаем ТОЛЬКО при auth-ошибках
                if exc.status_code in {401, 403} and index < len(api_keys):
                    continue

                # На 429 (rate limit / quota) НЕ надо переключать ключи автоматом.
                # Иначе ты получаешь "429, потом 401" из-за случайно битого запасного ключа.
                raise

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

        with httpx.Client(timeout=timeout) as client:
            while True:
                try:
                    response = client.post(
                        url,
                        json=json_payload,
                        headers=headers,
                        params=params,
                    )
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

                status = response.status_code
                if 200 <= status < 300:
                    try:
                        return response.json()
                    except ValueError:
                        # Успешный статус, но не JSON (редко, но лучше обработать)
                        raise LLMProviderError(
                            "LLM provider returned non-JSON response",
                            status_code=status,
                            retryable=False,
                            fallback=True,
                            category="bad_response",
                        )

                # Ошибочный статус
                if status in retry_statuses and attempts < max_retries:
                    attempts += 1
                    retry_after = self._retry_after_seconds(response)
                    self._sleep_backoff(attempts, retry_after=retry_after)
                    continue

                retryable = status in retry_statuses or status >= 500
                fallback = status in fallback_statuses or status >= 500
                category = self._status_category(status)
                message = self._format_error_message(status, response)

                raise LLMProviderError(
                    message,
                    status_code=status,
                    retryable=retryable,
                    fallback=fallback,
                    category=category,
                )

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        # Поддерживаем стандартный Retry-After (обычно секунды).
        val = response.headers.get("retry-after")
        if not val:
            return None
        try:
            return float(val.strip())
        except ValueError:
            return None

    @staticmethod
    def _sleep_backoff(attempt: int, *, retry_after: float | None = None) -> None:
        # Если сервер просит подождать конкретно — соблюдаем это.
        if retry_after is not None:
            # минимальный "пол" чтобы не улетать в 0 при округлениях
            time.sleep(max(0.2, retry_after))
            return
        # Иначе — простой backoff
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
    def _format_error_message(status: int, response: httpx.Response) -> str:
        # Стараемся вытащить “человеческую” причину из JSON ошибки
        text_snippet = ""
        try:
            data = response.json()
            # OpenAI обычно: {"error": {"message": "...", "type": "...", "code": "..."}}
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    msg = err.get("message")
                    code = err.get("code")
                    typ = err.get("type")
                    parts: list[str] = []
                    if msg:
                        parts.append(str(msg))
                    if typ:
                        parts.append(f"type={typ}")
                    if code:
                        parts.append(f"code={code}")
                    if parts:
                        text_snippet = " | ".join(parts)
                # Gemini/Google APIs часто: {"error": {"message": "...", "status": "..."}}
                if not text_snippet and isinstance(data.get("error"), dict):
                    msg = data["error"].get("message")
                    stat = data["error"].get("status")
                    if msg or stat:
                        text_snippet = f"{msg or ''}".strip()
                        if stat:
                            text_snippet = f"{text_snippet} | status={stat}".strip(" |")
        except Exception:
            # не JSON или неожиданная структура
            pass

        if not text_snippet:
            # fallback на обычный текст, но ограничиваем длину
            try:
                raw = response.text or ""
                raw = raw.replace("\n", " ").strip()
                text_snippet = raw[:300]
            except Exception:
                text_snippet = ""

        if text_snippet:
            return f"LLM provider returned status {status}: {text_snippet}"
        return f"LLM provider returned status {status}"

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
