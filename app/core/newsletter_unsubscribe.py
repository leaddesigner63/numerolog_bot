from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import urlencode


def _urlsafe_b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _urlsafe_b64decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}".encode("utf-8"))


def generate_unsubscribe_token(*, user_id: int, issued_at: int, secret: str) -> str:
    payload = {
        "user_id": user_id,
        "issued_at": issued_at,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_part = _urlsafe_b64encode(payload_bytes)
    signature = hmac.new(secret.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    signature_part = _urlsafe_b64encode(signature)
    return f"{payload_part}.{signature_part}"


def verify_unsubscribe_token(token: str, *, secret: str) -> dict[str, Any] | None:
    if not token or "." not in token or not secret:
        return None

    payload_part, signature_part = token.split(".", 1)
    expected_signature = hmac.new(
        secret.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256
    ).digest()

    try:
        provided_signature = _urlsafe_b64decode(signature_part)
    except Exception:
        return None

    if not hmac.compare_digest(expected_signature, provided_signature):
        return None

    try:
        payload_raw = _urlsafe_b64decode(payload_part)
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    if "user_id" not in payload or "issued_at" not in payload:
        return None
    return payload


def build_unsubscribe_url(*, base_url: str, token: str) -> str:
    query = urlencode({"token": token})
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{query}"
