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


class ProdamusWebhookError(ValueError):
    """Base verification error for Prodamus webhooks."""

    event_code = "prodamus_webhook_invalid"


class ProdamusMissingSecretError(ProdamusWebhookError):
    event_code = "prodamus_webhook_missing_secret"


class ProdamusMissingSignatureError(ProdamusWebhookError):
    event_code = "prodamus_webhook_missing_signature"


class ProdamusSignatureMismatchError(ProdamusWebhookError):
    event_code = "prodamus_webhook_signature_mismatch"


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
        order_email = getattr(order, "email", "") or ""
        order_phone = getattr(order, "phone", "") or ""
        order_customer_name = getattr(order, "customer_name", "") or ""

        if user is not None:
            user_email = getattr(user, "email", "") or ""
            user_phone = getattr(user, "phone", "") or ""
            user_name = getattr(user, "name", "") or getattr(user, "telegram_username", "") or ""
            order_email = order_email or user_email
            order_phone = order_phone or user_phone
            order_customer_name = order_customer_name or user_name

        order_title = getattr(order, "title", "") or f"Тариф {getattr(order.tariff, 'value', order.tariff)}"

        success_url = _as_non_empty_str(getattr(self._settings, "payment_success_url", None))
        fail_url = _as_non_empty_str(getattr(self._settings, "payment_fail_url", None))
        webhook_url = _as_non_empty_str(getattr(self._settings, "payment_webhook_url", None))

        params: dict[str, str] = {
            "order_id": str(order.id),
            "amount": f"{order.amount:.2f}",
            "sum": f"{order.amount:.2f}",
            "customer_email": order_email,
            "customer_phone": order_phone,
            "customer_extra": order_customer_name,
            "customer_id": str(getattr(user, "telegram_user_id", "") or ""),
            "customer_username": str(getattr(user, "telegram_username", "") or ""),
            "products[0][name]": order_title,
            "products[0][price]": f"{order.amount:.2f}",
            "products[0][quantity]": "1",
            "products[0][sum]": f"{order.amount:.2f}",
            "success_url": success_url,
            "fail_url": fail_url,
            "callback_url": webhook_url,
            # Backward-compatible aliases used by some Prodamus form presets.
            "urlSuccess": success_url,
            "urlReturn": fail_url,
            "urlNotification": webhook_url,
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
        allow_unsigned = bool(getattr(self._settings, "prodamus_allow_unsigned_webhook", False))

        signature_data = _find_signature(headers, payload)
        if not secret:
            if not (allow_unsigned and _allow_unsigned_payload(payload=payload, headers=headers, settings=self._settings)):
                logger.warning("prodamus_webhook_missing_secret", extra={"event_code": ProdamusMissingSecretError.event_code})
                raise ProdamusMissingSecretError("Prodamus webhook secret is not configured")
            logger.warning("prodamus_webhook_unsigned_fallback_accepted", extra={"event_code": "prodamus_webhook_unsigned_fallback_accepted"})
        else:
            if signature_data:
                if not _matches_signature(
                    signature=signature_data[0],
                    secret=secret,
                    payload=payload,
                    raw_body=raw_body,
                ):
                    logger.warning("prodamus_webhook_signature_mismatch", extra={"event_code": ProdamusSignatureMismatchError.event_code})
                    raise ProdamusSignatureMismatchError("Prodamus signature mismatch")
            elif _matches_payload_secret(payload, secret):
                pass
            elif allow_unsigned and _allow_unsigned_payload(payload=payload, headers=headers, settings=self._settings):
                logger.warning("prodamus_webhook_unsigned_fallback_accepted", extra={"event_code": "prodamus_webhook_unsigned_fallback_accepted"})
            else:
                logger.warning("prodamus_webhook_missing_signature", extra={"event_code": ProdamusMissingSignatureError.event_code})
                raise ProdamusMissingSignatureError("Prodamus signature is missing")

        webhook = _extract_webhook(payload)
        return WebhookResult(
            order_id=webhook.order_id,
            provider_payment_id=webhook.payment_id,
            is_paid=webhook.is_paid,
            status=webhook.status,
            verified=bool(secret and (signature_data or _matches_payload_secret(payload, secret))),
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
        if self._key and "do" not in params:
            params = dict(params)
            params["do"] = "link"
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

    for key in ("sign", "signature", "x-sign", "x-signature", "x-prodamus-signature", "x-prodamus-sign"):
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

    # 5) Legacy compatibility seen in older integrations: md5(secret + raw_body)
    try:
        legacy_raw = hashlib.md5(secret.encode("utf-8") + raw_body).hexdigest()
        if hmac.compare_digest(legacy_raw.lower(), sig.lower()):
            return True
    except Exception:
        pass

    return False


def _matches_payload_secret(payload: Mapping[str, Any], secret: str) -> bool:
    """Compatibility mode: secret passed inside payload (not recommended)."""
    value = payload.get("secret")
    return bool(value) and str(value) == secret


def _allow_unsigned_payload(payload: Mapping[str, Any], headers: Mapping[str, str], settings: Settings) -> bool:
    if not payload.get("order_id"):
        return False

    payload_secret = getattr(settings, "prodamus_unsigned_payload_secret", None)
    if payload_secret:
        incoming_payload_secret = payload.get("secret")
        if str(incoming_payload_secret or "") != str(payload_secret):
            return False

    whitelist = _split_csv(getattr(settings, "prodamus_unsigned_webhook_ips", None))
    if not whitelist:
        return False

    remote_ip = _extract_remote_ip(headers)
    return bool(remote_ip and remote_ip in whitelist)


def _split_csv(value: str | None) -> set[str]:
    if not value:
        return set()
    return {part.strip() for part in str(value).split(",") if part.strip()}


def _extract_remote_ip(headers: Mapping[str, str]) -> str:
    lowered = {str(k).lower(): str(v) for k, v in headers.items()}
    forwarded = lowered.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return lowered.get("x-real-ip", "").strip()


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
    html_link = _extract_payment_link_from_html(resp.text)
    if html_link:
        return html_link

    # Some Prodamus setups return just a plain-text URL (without HTML wrappers).
    return _extract_direct_url_from_text(resp.text)


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


def _extract_direct_url_from_text(text: str) -> str | None:
    for raw_url in re.findall(r"https?://[^\s\"'<>]+", text, flags=re.IGNORECASE):
        url = raw_url.rstrip(".,;)")
        if url:
            return url
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
    order_data = payload.get("order") if isinstance(payload.get("order"), Mapping) else {}
    payment_data = payload.get("payment") if isinstance(payload.get("payment"), Mapping) else {}
    result_data = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}

    nested_order_data = result_data.get("order") if isinstance(result_data.get("order"), Mapping) else {}
    nested_payment_data = result_data.get("payment") if isinstance(result_data.get("payment"), Mapping) else {}

    order_id_raw = payload.get("order_id") or order_data.get("id") or nested_order_data.get("id")
    payment_id = (
        payload.get("payment_id")
        or payload.get("invoice_id")
        or payload.get("transaction_id")
        or payment_data.get("id")
        or nested_payment_data.get("id")
    )
    status = payload.get("payment_status") or payload.get("status") or payment_data.get("state") or nested_payment_data.get("state")

    order_id: int | None = None
    if order_id_raw is not None:
        try:
            order_id = int(str(order_id_raw))
        except (TypeError, ValueError):
            raise ValueError("order_id is invalid in Prodamus payload")

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


def _as_non_empty_str(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return "" if text in ("", "None") else text
