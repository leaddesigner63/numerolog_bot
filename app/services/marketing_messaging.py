from __future__ import annotations

import logging
from dataclasses import dataclass
from time import time

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.newsletter_unsubscribe import (
    build_unsubscribe_url,
    generate_unsubscribe_token,
)
from app.db.models import User, UserProfile

logger = logging.getLogger(__name__)


@dataclass
class MarketingSendResult:
    sent: bool
    reason: str
    consent_version: str | None = None
    has_unsubscribe_link: bool = False


def generate_personal_unsubscribe_link(*, user_id: int, secret: str | None = None) -> str | None:
    unsubscribe_secret = secret or settings.newsletter_unsubscribe_secret
    base_url = settings.newsletter_unsubscribe_base_url
    if not unsubscribe_secret or not base_url:
        return None

    token = generate_unsubscribe_token(
        user_id=user_id,
        issued_at=int(time()),
        secret=unsubscribe_secret,
    )
    return build_unsubscribe_url(base_url=base_url, token=token)


def append_unsubscribe_block(*, message_text: str, unsubscribe_link: str | None) -> str:
    if not unsubscribe_link:
        return message_text
    return f"{message_text}\n\nОтписаться: {unsubscribe_link}"


def _classify_telegram_send_error(exc: Exception) -> str:
    if isinstance(exc, TelegramForbiddenError):
        return "telegram_forbidden"
    if isinstance(exc, TelegramNotFound):
        return "telegram_chat_not_found"
    if isinstance(exc, TelegramRetryAfter):
        return "telegram_rate_limited"
    if isinstance(exc, TelegramNetworkError):
        return "telegram_network_error"
    if isinstance(exc, TimeoutError):
        return "telegram_timeout"
    if isinstance(exc, TelegramBadRequest):
        return "telegram_bad_request"
    return "telegram_send_failed"


async def send_marketing_message(
    *,
    bot: Bot,
    session: Session,
    user_id: int,
    campaign: str,
    message_text: str,
) -> MarketingSendResult:
    profile = session.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    ).scalar_one_or_none()
    if profile is None:
        return MarketingSendResult(sent=False, reason="profile_not_found")

    consent_version = profile.marketing_consent_document_version
    if profile.marketing_consent_revoked_at is not None:
        logger.info(
            "marketing_message_skipped",
            extra={
                "campaign": campaign,
                "user_id": user_id,
                "reason": "consent_revoked",
                "consent_version": consent_version,
                "has_unsubscribe_link": False,
            },
        )
        return MarketingSendResult(
            sent=False,
            reason="consent_revoked",
            consent_version=consent_version,
            has_unsubscribe_link=False,
        )

    user = session.get(User, user_id)
    if user is None:
        return MarketingSendResult(sent=False, reason="user_not_found", consent_version=consent_version)

    unsubscribe_link = generate_personal_unsubscribe_link(user_id=user_id)
    has_unsubscribe_link = bool(unsubscribe_link)
    prepared_text = append_unsubscribe_block(
        message_text=message_text,
        unsubscribe_link=unsubscribe_link,
    )

    try:
        await bot.send_message(chat_id=user.telegram_user_id, text=prepared_text)
    except Exception as exc:  # noqa: BLE001
        reason = _classify_telegram_send_error(exc)
        retry_after = getattr(exc, "retry_after", None)
        logger.warning(
            "marketing_message_send_failed",
            extra={
                "campaign": campaign,
                "user_id": user_id,
                "telegram_user_id": user.telegram_user_id,
                "reason": reason,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "retry_after": retry_after,
                "is_timeout": isinstance(exc, TimeoutError),
                "consent_version": consent_version,
                "has_unsubscribe_link": has_unsubscribe_link,
            },
            exc_info=not isinstance(exc, (TelegramForbiddenError, TelegramNotFound, TelegramRetryAfter, TelegramNetworkError, TelegramBadRequest, TimeoutError)),
        )
        return MarketingSendResult(
            sent=False,
            reason=reason,
            consent_version=consent_version,
            has_unsubscribe_link=has_unsubscribe_link,
        )

    logger.info(
        "marketing_message_sent",
        extra={
            "campaign": campaign,
            "user_id": user_id,
            "telegram_user_id": user.telegram_user_id,
            "consent_version": consent_version,
            "has_unsubscribe_link": has_unsubscribe_link,
        },
    )
    return MarketingSendResult(
        sent=True,
        reason="sent",
        consent_version=consent_version,
        has_unsubscribe_link=has_unsubscribe_link,
    )
