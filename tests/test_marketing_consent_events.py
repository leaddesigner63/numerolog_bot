import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.handlers import profile
from app.db.base import Base
from app.db.models import MarketingConsentEvent, MarketingConsentEventType, User, UserProfile


class MarketingConsentEventHandlersTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

        @contextmanager
        def _test_get_session():
            session = self.SessionLocal()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        self._old_get_session = profile.get_session
        profile.get_session = _test_get_session

        with self.SessionLocal() as session:
            user = User(id=1, telegram_user_id=1001, telegram_username="tester")
            session.add(user)
            session.flush()
            session.add(
                UserProfile(
                    user_id=user.id,
                    name="Иван",
                    birth_date="2000-01-01",
                    birth_time="10:00",
                    birth_place_city="Москва",
                    birth_place_region="Московская область",
                    birth_place_country="Россия",
                )
            )
            session.commit()

    def tearDown(self) -> None:
        profile.get_session = self._old_get_session
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    async def test_accept_marketing_consent_writes_event(self) -> None:
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=1001, username="tester"),
            answer=AsyncMock(),
        )

        await profile.accept_marketing_consent(callback)

        with self.SessionLocal() as session:
            db_profile = session.execute(select(UserProfile).where(UserProfile.user_id == 1)).scalar_one()
            self.assertIsNotNone(db_profile.marketing_consent_accepted_at)
            self.assertEqual(db_profile.marketing_consent_source, "profile_flow")
            self.assertEqual(db_profile.marketing_consent_document_version, "v1")

            events = session.execute(select(MarketingConsentEvent).order_by(MarketingConsentEvent.id)).scalars().all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, MarketingConsentEventType.ACCEPTED)
            self.assertEqual(events[0].source, "profile_flow")

    async def test_revoke_marketing_consent_writes_event(self) -> None:
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=1001, username="tester"),
            answer=AsyncMock(),
        )

        await profile.accept_marketing_consent(callback)
        await profile.revoke_marketing_consent(callback)

        with self.SessionLocal() as session:
            db_profile = session.execute(select(UserProfile).where(UserProfile.user_id == 1)).scalar_one()
            self.assertIsNotNone(db_profile.marketing_consent_revoked_at)
            self.assertEqual(db_profile.marketing_consent_revoked_source, "profile_flow")

            events = session.execute(select(MarketingConsentEvent).order_by(MarketingConsentEvent.id)).scalars().all()
            self.assertEqual(len(events), 2)
            self.assertEqual(events[1].event_type, MarketingConsentEventType.REVOKED)
            self.assertEqual(events[1].source, "profile_flow")


if __name__ == "__main__":
    unittest.main()
