from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
import re
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode

import httpx

from app.core.config import Settings
from app.payments.base import PaymentProvider, WebhookResult, PaymentLinkResult
from app.db.models import PaymentProvider as PaymentProviderEnum, Order, User

logger = logging.getLogger(__name__)


@dataclass
class ProdamusSettings:
    prodamus_form_url: str
    prodamus_unified_key: str | None = None


class ProdamusProvider(PaymentProvider):
    provider = PaymentProviderEnum.PRODAMUS

    def __init__(self, settings: Settings):
        self._settings = settings
        # unified key (also used as webhook secret by default, unless a dedicated secret is configured)
        self._key = getattr(settings, "prodamus_unified_key", None)

    def create_payment_link(self, order: Order, user: User | None = None) -> PaymentLinkResult:
        # Payment form url
        if not getattr(self._settings, "prodamus_form_url", None):
            raise ValueError("Missing prodamus_form_url")

        # For PayForm "link" generation the unified key is used as 'key' parameter.
        # (Some configs can generate link without signature, Prodamus validates by key + params.)
        params: dict[str, str] = {
            "order_id": str(order.id),
            "customer_email": order.email or "",
            "customer_phone": order.phone or "",
            "customer_extra": order.customer_name or "",
            "products[0][name]": order.title or f"Order #{order.id}",
            "products[0][price]": f"{order.amount:.2f}",
            "products[0][quantity]": "1",
            "urlSuccess": getattr(self._settings, "payment_success_url", ""),
            "urlReturn": getattr(self._settings, "payment_return_url", ""),
            "urlNotification": getattr(self._settings, "payment_webhook_url", ""),
        }

        # Filter empty
        params = {k: v for k, v in params.items() if v != ""}

        # Generate a link.
        link = self._create_api_generated_payment_link(params)
        if not link:
            # Fallback: build query url
            link = self._build_form_link(params)

        return PaymentLinkResult(url=link, provider=self.provider)

    def check_payment_status(self, order: Order) -> WebhookResult | None:
        """MVP: активная проверка статуса в Prodamus не используется.

        Подтверждение оплаты идёт через webhook, поэтому метод возвращает `None`.
        """

        return None

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookResult:
        payload = _parse_payload(raw_body)

        # Prefer dedicated webhook secret if available; fallback to unified key.
        secret = getattr(self._settings, "prodamus_webhook_secret", None) or getattr(
            self._settings, "prodamus_notify_secret", None
        ) or self._key

        if secret:
            signature_data = _find_signature(headers, payload)
            if signature_data:
                if not _matches_signature(
                    signature=signature_data[0],
                    secret=secret,
                    payload=payload,
                    raw_body=raw_body,
                ):
                    raise ValueError(f"Invalid Prodamus signature from {signature_data[1]}")
            else:
                if not _matches_payload_secret(payload, secret):
                    raise ValueError("Missing Prodamus signature (header Sign)")
        else:
            logger.warning("Prodamus secret key not configured; webhook verification skipped")

        webhook = _extract_webhook(payload)
        return WebhookResult(
            order_id=webhook.order_id,
            provider_payment_id=webhook.payment_id,
            is_paid=webhook.is_paid,
            status=webhook.status,
            verified=bool(secret),
        )

    def _build_form_link(self, params: dict[str, str]) -> str:
        # Standard Prodamus form link:
        # https://payform.prodamus.ru/?order_id=...&products[0][name]=...&...
        # The unified key is typically passed as key=... (or configured in the form settings).
        base = self._settings.prodamus_form_url.rstrip("?")
        # Some setups require key:
        if self._key and "key" not in params:
            params = dict(params)
            params["key"] = self._key
        return f"{base}?{urlencode(params)}"

    def _create_api_generated_payment_link(self, params: dict[str, str]) -> str | None:
        # For API-generated link, Prodamus expects do=link & key=... and returns HTML/JSON containing a payment link.
        api_params = dict(params)
        if self._key:
            api_params["key"] = self._key
        api_params["do"] = "link"

        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.get(self._settings.prodamus_form_url, params=api_params)
                resp.raise_for_status()
        except httpx.HTTPError:
            return None

        return _extract_payment_link_from_response(resp)


def _find_signature(headers: Mapping[str, str], payload: Mapping[str, Any]) -> tuple[str, str] | None:
    """Extract signature from headers or payload.

    Prodamus PayForm URL notifications provide signature in header `Sign`.
    We also accept common alternates for compatibility.
    """
    lowered = {str(k).lower(): str(v) for k, v in headers.items()}

    for key in ("sign", "x-sign", "x-signature", "x-prodamus-signature", "x-prodamus-sign"):
        value = lowered.get(key)
        if value:
            value = value.strip()
            if value:
                return value, f"header:{key}"

    for key in ("sign", "signature"):
        if key in payload and payload[key]:
            return str(payload[key]).strip(), f"payload:{key}"

    return None


def _canonical_signature(secret: str, payload: Mapping[str, Any]) -> str:
    """Compute canonical Prodamus signature (HMAC-SHA256).

    According to Prodamus PayForm docs for URL notifications:
    1) Cast all values to strings
    2) Sort keys recursively (depth-first)
    3) Convert to JSON string
    4) Escape '/' as '\/'
    5) Sign JSON with HMAC-SHA256 using the secret key
    """
    json_data = _canonical_json_for_sign(payload)
    return hmac.new(secret.encode("utf-8"), json_data.encode("utf-8"), hashlib.sha256).hexdigest()


def _matches_signature(signature: str, secret: str, payload: Mapping[str, Any], raw_body: bytes) -> bool:
    sig = signature.strip()
    if not sig:
        return False

    # 1) Official signature (HMAC-SHA256 over canonical JSON)
    try:
        expected = _canonical_signature(secret, payload)
        if hmac.compare_digest(expected.lower(), sig.lower()):
            return True
    except Exception:
        pass

    # 2) Legacy compatibility: MD5(token + secret) if token exists
    token = payload.get("token")
    if token:
        legacy = hashlib.md5((str(token) + secret).encode("utf-8")).hexdigest()
        if hmac.compare_digest(legacy.lower(), sig.lower()):
            return True

    # 3) Rare compatibility: base64(HMAC-SHA256)
    try:
        expected = _canonical_signature(secret, payload)
        b64 = base64.b64encode(bytes.fromhex(expected)).decode("ascii")
        if hmac.compare_digest(b64.strip(), sig):
            return True
    except Exception:
        pass

    # 4) Extremely rare: HMAC-SHA256 over raw body bytes
    try:
        raw_expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(raw_expected.lower(), sig.lower()):
            return True
    except Exception:
        pass

    return False


def _matches_payload_secret(payload: Mapping[str, Any], secret: str) -> bool:
    """Compatibility mode: secret passed inside payload (not recommended)."""
    value = payload.get("secret")
    return bool(value) and str(value) == secret


def _extract_payment_link_from_response(resp: httpx.Response) -> str | None:
    # Try JSON
    try:
        data = resp.json()
        link = _extract_payment_link_from_json(data)
        if link:
            return link
    except json.JSONDecodeError:
        pass

    # Try HTML/text
    return _extract_payment_link_from_html(resp.text)


def _extract_payment_link_from_html(html: str) -> str | None:
    # Most common patterns:
    # - href="https://payform.prodamus.ru/...."
    # - location.href='...'
    # - window.location="..."
    # - data-url="..."
    patterns = [
        r'href=["\'](https?://[^"\']+)["\']',
        r"location\.href\s*=\s*['\"](https?://[^'\"]+)['\"]",
        r"window\.location\s*=\s*['\"](https?://[^'\"]+)['\"]",
        r'data-url=["\'](https?://[^"\']+)["\']',
    ]

    for pat in patterns:
        m = re.search(pat, html, flags=re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _extract_payment_link_from_json(data: Any) -> str | None:
    if isinstance(data, dict):
        for key in ("url", "payment_url", "paymentLink", "payment_link", "link", "redirect_url"):
            if key in data and isinstance(data[key], str) and data[key].startswith(("http://", "https://")):
                return data[key]
        # nested
        for v in data.values():
            found = _extract_payment_link_from_json(v)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_payment_link_from_json(item)
            if found:
                return found
    return None


def _parse_payload(raw_body: bytes) -> dict[str, Any]:
    """Parse incoming webhook body.

    Prodamus PayForm sends URL-encoded form data and uses PHP-style bracket keys, e.g.:
    products[0][name]=...&products[0][price]=...

    We convert such keys into nested dict/list structures to match PHP's $_POST
    representation (required for correct signature verification).
    """
    if not raw_body:
        return {}

    stripped = raw_body.lstrip()
    if stripped.startswith(b"{") or stripped.startswith(b"["):
        try:
            data = json.loads(raw_body.decode("utf-8"))
            return data if isinstance(data, dict) else {"_": data}
        except Exception:
            pass

    try:
        text = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        text = raw_body.decode("latin-1", errors="replace")

    pairs = parse_qsl(text, keep_blank_values=True)
    return _unflatten_bracket_pairs(pairs)


def _unflatten_bracket_pairs(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for key, value in pairs:
        parts = _split_bracket_key(key)
        _set_by_parts(root, parts, value)
    return _prune_none(root)


def _split_bracket_key(key: str) -> list[str]:
    if "[" not in key:
        return [key]
    base = key.split("[", 1)[0]
    parts = [base]
    parts.extend(m.group(1) for m in re.finditer(r"\[([^\]]*)\]", key))
    return parts


def _set_by_parts(root: Any, parts: list[str], value: str) -> None:
    cur: Any = root
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        next_part = parts[i + 1] if not last else None

        if isinstance(cur, dict):
            if last:
                cur[part] = value
                return
            if part not in cur or cur[part] is None:
                cur[part] = [] if (next_part == "" or (next_part or "").isdigit()) else {}
            cur = cur[part]
            continue

        if isinstance(cur, list):
            # Empty brackets mean append (PHP-style): items[][name]
            if part == "":
                if last:
                    cur.append(value)
                    return
                container: Any = [] if (next_part == "" or (next_part or "").isdigit()) else {}
                cur.append(container)
                cur = container
                continue

            idx = int(part) if part.isdigit() else len(cur)
            while len(cur) <= idx:
                cur.append(None)

            if last:
                cur[idx] = value
                return

            if cur[idx] is None:
                cur[idx] = [] if (next_part == "" or (next_part or "").isdigit()) else {}
            cur = cur[idx]
            continue

        # Unknown container, stop best-effort
        return


def _prune_none(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _prune_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_prune_none(v) for v in obj if v is not None]
    return obj


def _canonical_json_for_sign(payload: Mapping[str, Any]) -> str:
    normalized = _normalize_payload(payload)
    sorted_payload = _deep_sort(normalized)
    json_data = json.dumps(sorted_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    return json_data.replace("/", "\\/")


def _normalize_payload(obj: Any) -> Any:
    """Recursively cast values to strings (and drop None)."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            nv = _normalize_payload(v)
            if nv is not None:
                out[str(k)] = nv
        return out
    if isinstance(obj, list):
        out_list: list[Any] = []
        for v in obj:
            nv = _normalize_payload(v)
            if nv is not None:
                out_list.append(nv)
        return out_list
    if isinstance(obj, bool):
        # PHP strval(true) -> "1", strval(false) -> ""
        return "1" if obj else ""
    return str(obj)


def _deep_sort(obj: Any) -> Any:
    """Recursively sort dict keys lexicographically (stable)."""
    if isinstance(obj, dict):
        return {k: _deep_sort(obj[k]) for k in sorted(obj.keys(), key=lambda x: str(x))}
    if isinstance(obj, list):
        return [_deep_sort(v) for v in obj]
    return obj


def _is_paid_status(status: str | None) -> bool:
    if not status:
        return False
    s = str(status).strip().lower()
    return s in ("paid", "success", "succeeded", "ok", "completed", "1", "true", "yes")


@dataclass
class _Webhook:
    order_id: int | None
    payment_id: str | None
    status: str | None
    is_paid: bool


def _extract_webhook(payload: Mapping[str, Any]) -> _Webhook:
    # Common Prodamus fields:
    # - order_id
    # - payment_id
    # - payment_status
    order_id_raw = payload.get("order_id")
    payment_id = payload.get("payment_id") or payload.get("invoice_id") or payload.get("transaction_id")
    status = payload.get("payment_status") or payload.get("status")

    order_id: int | None = None
    if order_id_raw is not None:
        try:
            order_id = int(str(order_id_raw))
        except (TypeError, ValueError):
            order_id = None

    is_paid = False
    # Some payloads include "paid" flag
    paid_flag = payload.get("paid")
    if paid_flag is not None:
        is_paid = str(paid_flag).strip().lower() in ("1", "true", "yes", "paid", "success", "ok")
    else:
        is_paid = _is_paid_status(str(status) if status is not None else None)

    return _Webhook(
        order_id=order_id,
        payment_id=str(payment_id) if payment_id is not None else None,
        status=str(status) if status is not None else None,
        is_paid=is_paid,
    )
