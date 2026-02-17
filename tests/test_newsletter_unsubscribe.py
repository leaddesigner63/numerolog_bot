from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.newsletter_unsubscribe import generate_unsubscribe_token, verify_unsubscribe_token
from app.db.base import Base
from app.db.models import MarketingConsentEvent, MarketingConsentEventType, User, UserProfile
from app.main import create_app


def test_unsubscribe_token_sign_and_verify() -> None:
    token = generate_unsubscribe_token(user_id=77, issued_at=1730000000, secret="secret")

    payload = verify_unsubscribe_token(token, secret="secret")

    assert payload == {"user_id": 77, "issued_at": 1730000000}
    assert verify_unsubscribe_token(token, secret="another-secret") is None


def test_newsletter_unsubscribe_api_valid_token_revokes_consent_and_writes_history(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        user = User(telegram_user_id=5001, telegram_username="user")
        session.add(user)
        session.flush()
        session.add(
            UserProfile(
                user_id=user.id,
                name="Name",
                gender="f",
                birth_date="01.01.2000",
                birth_time=None,
                birth_place_city="Moscow",
                birth_place_region=None,
                birth_place_country="RU",
                marketing_consent_accepted_at=datetime.now(timezone.utc),
                marketing_consent_document_version="v1",
                marketing_consent_source="marketing_prompt",
            )
        )
        session.commit()
        user_id = user.id

    @contextmanager
    def fake_get_session():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("app.api.routes.public.get_session", fake_get_session)
    monkeypatch.setattr("app.api.routes.public.settings.newsletter_unsubscribe_secret", "secret")
    monkeypatch.setattr(
        "app.api.routes.public.settings.newsletter_consent_document_version", "v9"
    )

    app = create_app()
    client = TestClient(app)

    token = generate_unsubscribe_token(user_id=user_id, issued_at=1730000000, secret="secret")
    response = client.get("/newsletter/unsubscribe", params={"token": token})

    assert response.status_code == 200
    assert "Вы отписаны" in response.text

    with SessionLocal() as session:
        profile = session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        ).scalar_one()
        assert profile.marketing_consent_accepted_at is None
        assert profile.marketing_consent_revoked_at is not None
        assert profile.marketing_consent_revoked_source == "unsubscribe_link"

        event = session.execute(select(MarketingConsentEvent)).scalar_one()
        assert event.event_type == MarketingConsentEventType.REVOKED
        assert event.source == "unsubscribe_link"
        assert event.document_version == "v1"
        assert event.metadata_json["issued_at"] == 1730000000

    Base.metadata.drop_all(engine)


def test_newsletter_unsubscribe_api_invalid_token_returns_400(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.public.settings.newsletter_unsubscribe_secret", "secret")

    app = create_app()
    client = TestClient(app)

    response = client.get("/newsletter/unsubscribe", params={"token": "invalid"})

    assert response.status_code == 400
    assert "Ссылка недействительна" in response.text


def test_newsletter_unsubscribe_repeat_click_is_idempotent(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        user = User(telegram_user_id=5002, telegram_username="user2")
        session.add(user)
        session.flush()
        session.add(
            UserProfile(
                user_id=user.id,
                name="Name",
                gender="f",
                birth_date="01.01.2000",
                birth_time=None,
                birth_place_city="Moscow",
                birth_place_region=None,
                birth_place_country="RU",
                marketing_consent_accepted_at=datetime.now(timezone.utc),
                marketing_consent_document_version="v1",
                marketing_consent_source="marketing_prompt",
            )
        )
        session.commit()
        user_id = user.id

    @contextmanager
    def fake_get_session():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("app.api.routes.public.get_session", fake_get_session)
    monkeypatch.setattr("app.api.routes.public.settings.newsletter_unsubscribe_secret", "secret")

    app = create_app()
    client = TestClient(app)

    token = generate_unsubscribe_token(user_id=user_id, issued_at=1730000000, secret="secret")

    response_first = client.get("/newsletter/unsubscribe", params={"token": token})
    response_second = client.get("/newsletter/unsubscribe", params={"token": token})

    assert response_first.status_code == 200
    assert response_second.status_code == 200

    with SessionLocal() as session:
        events = session.execute(
            select(MarketingConsentEvent).where(MarketingConsentEvent.user_id == user_id)
        ).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == MarketingConsentEventType.REVOKED

    Base.metadata.drop_all(engine)
