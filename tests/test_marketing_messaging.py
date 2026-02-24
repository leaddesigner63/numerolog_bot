import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramNotFound
from aiogram.methods import SendMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.models import User, UserProfile
from app.services.marketing_messaging import (
    append_unsubscribe_block,
    generate_personal_unsubscribe_link,
    send_marketing_message,
)


def _create_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine), engine


def test_generate_personal_unsubscribe_link() -> None:
    original_base_url = settings.newsletter_unsubscribe_base_url
    original_secret = settings.newsletter_unsubscribe_secret
    settings.newsletter_unsubscribe_base_url = "https://example.com/newsletter/unsubscribe"
    settings.newsletter_unsubscribe_secret = "secret"

    link = generate_personal_unsubscribe_link(user_id=42)

    assert link is not None
    assert link.startswith("https://example.com/newsletter/unsubscribe?token=")

    settings.newsletter_unsubscribe_base_url = original_base_url
    settings.newsletter_unsubscribe_secret = original_secret


def test_append_unsubscribe_block() -> None:
    text = append_unsubscribe_block(
        message_text="Ваша персональная акция",
        unsubscribe_link="https://example.com/u",
    )

    assert text.endswith("Отписаться: https://example.com/u")


def test_marketing_template_contains_unsubscribe_link() -> None:
    prepared = append_unsubscribe_block(
        message_text="Персональная подборка на неделю",
        unsubscribe_link="https://example.com/newsletter/unsubscribe?token=abc",
    )

    assert "Отписаться:" in prepared
    assert "https://example.com/newsletter/unsubscribe?token=abc" in prepared


def test_send_marketing_message_skips_revoked_consent() -> None:
    SessionLocal, engine = _create_session_factory()
    with SessionLocal() as session:
        user = User(telegram_user_id=10001, telegram_username="revoked")
        session.add(user)
        session.flush()
        session.add(
            UserProfile(
                user_id=user.id,
                name="N",
                gender=None,
                birth_date="01.01.2000",
                birth_time=None,
                birth_place_city="Moscow",
                birth_place_region=None,
                birth_place_country="RU",
                marketing_consent_accepted_at=datetime.now(timezone.utc),
                marketing_consent_revoked_at=datetime.now(timezone.utc),
                marketing_consent_document_version="v7",
            )
        )
        session.commit()
        user_id = user.id

    bot = AsyncMock(spec=Bot)
    with SessionLocal() as session:
        result = asyncio.run(
            send_marketing_message(
                bot=bot,
                session=session,
                user_id=user_id,
                campaign="winter_sale",
                message_text="Скидка 30%",
            )
        )

    assert result.sent is False
    assert result.reason == "consent_revoked"
    bot.send_message.assert_not_awaited()
    Base.metadata.drop_all(engine)


def test_send_marketing_message_adds_unsubscribe_link() -> None:
    original_base_url = settings.newsletter_unsubscribe_base_url
    original_secret = settings.newsletter_unsubscribe_secret
    settings.newsletter_unsubscribe_base_url = "https://example.com/newsletter/unsubscribe"
    settings.newsletter_unsubscribe_secret = "secret"

    SessionLocal, engine = _create_session_factory()
    with SessionLocal() as session:
        user = User(telegram_user_id=10002, telegram_username="active")
        session.add(user)
        session.flush()
        session.add(
            UserProfile(
                user_id=user.id,
                name="N",
                gender=None,
                birth_date="01.01.2000",
                birth_time=None,
                birth_place_city="Moscow",
                birth_place_region=None,
                birth_place_country="RU",
                marketing_consent_accepted_at=datetime.now(timezone.utc),
                marketing_consent_document_version="v9",
            )
        )
        session.commit()
        user_id = user.id

    bot = AsyncMock(spec=Bot)
    with SessionLocal() as session:
        result = asyncio.run(
            send_marketing_message(
                bot=bot,
                session=session,
                user_id=user_id,
                campaign="spring_sale",
                message_text="Новая подборка",
            )
        )

    assert result.sent is True
    assert result.consent_version == "v9"
    assert result.has_unsubscribe_link is True
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 10002
    assert "Отписаться:" in kwargs["text"]

    settings.newsletter_unsubscribe_base_url = original_base_url
    settings.newsletter_unsubscribe_secret = original_secret
    Base.metadata.drop_all(engine)


def test_send_marketing_message_handles_blocked_user() -> None:
    SessionLocal, engine = _create_session_factory()
    with SessionLocal() as session:
        user = User(telegram_user_id=10003, telegram_username="blocked")
        session.add(user)
        session.flush()
        session.add(
            UserProfile(
                user_id=user.id,
                name="N",
                gender=None,
                birth_date="01.01.2000",
                birth_time=None,
                birth_place_city="Moscow",
                birth_place_region=None,
                birth_place_country="RU",
                marketing_consent_accepted_at=datetime.now(timezone.utc),
                marketing_consent_document_version="v1",
            )
        )
        session.commit()
        user_id = user.id

    bot = AsyncMock(spec=Bot)
    bot.send_message.side_effect = TelegramForbiddenError(
        method=SendMessage(chat_id=10003, text="x"),
        message="Forbidden: bot was blocked by the user",
    )
    with SessionLocal() as session:
        result = asyncio.run(
            send_marketing_message(
                bot=bot,
                session=session,
                user_id=user_id,
                campaign="blocked_campaign",
                message_text="Тест",
            )
        )

    assert result.sent is False
    assert result.reason == "telegram_forbidden"
    Base.metadata.drop_all(engine)


def test_send_marketing_message_handles_chat_not_found() -> None:
    SessionLocal, engine = _create_session_factory()
    with SessionLocal() as session:
        user = User(telegram_user_id=10004, telegram_username="missing")
        session.add(user)
        session.flush()
        session.add(
            UserProfile(
                user_id=user.id,
                name="N",
                gender=None,
                birth_date="01.01.2000",
                birth_time=None,
                birth_place_city="Moscow",
                birth_place_region=None,
                birth_place_country="RU",
                marketing_consent_accepted_at=datetime.now(timezone.utc),
                marketing_consent_document_version="v1",
            )
        )
        session.commit()
        user_id = user.id

    bot = AsyncMock(spec=Bot)
    bot.send_message.side_effect = TelegramNotFound(
        method=SendMessage(chat_id=10004, text="x"),
        message="Not Found: chat not found",
    )
    with SessionLocal() as session:
        result = asyncio.run(
            send_marketing_message(
                bot=bot,
                session=session,
                user_id=user_id,
                campaign="missing_campaign",
                message_text="Тест",
            )
        )

    assert result.sent is False
    assert result.reason == "telegram_chat_not_found"
    Base.metadata.drop_all(engine)


def test_send_marketing_message_handles_timeout() -> None:
    SessionLocal, engine = _create_session_factory()
    with SessionLocal() as session:
        user = User(telegram_user_id=10005, telegram_username="timeout")
        session.add(user)
        session.flush()
        session.add(
            UserProfile(
                user_id=user.id,
                name="N",
                gender=None,
                birth_date="01.01.2000",
                birth_time=None,
                birth_place_city="Moscow",
                birth_place_region=None,
                birth_place_country="RU",
                marketing_consent_accepted_at=datetime.now(timezone.utc),
                marketing_consent_document_version="v1",
            )
        )
        session.commit()
        user_id = user.id

    bot = AsyncMock(spec=Bot)
    bot.send_message.side_effect = TimeoutError("timeout")
    with SessionLocal() as session:
        result = asyncio.run(
            send_marketing_message(
                bot=bot,
                session=session,
                user_id=user_id,
                campaign="timeout_campaign",
                message_text="Тест",
            )
        )

    assert result.sent is False
    assert result.reason == "telegram_timeout"
    Base.metadata.drop_all(engine)
