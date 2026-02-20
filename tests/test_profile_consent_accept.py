import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.handlers import profile
from app.db.base import Base
from app.db.models import (
    Order,
    OrderStatus,
    PaymentProvider,
    ReportJob,
    ReportJobStatus,
    Tariff,
    User,
    UserProfile,
    MarketingConsentEvent,
    MarketingConsentEventType,
)


class ProfileConsentAcceptTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_accept_consent_saves_profile_flag_and_opens_tariff_screen(self) -> None:
        callback = SimpleNamespace(
            bot=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id=5001), answer=AsyncMock()),
            from_user=SimpleNamespace(id=1001, username="tester"),
            answer=AsyncMock(),
        )

        for tariff_value, expected_screen in (
            (Tariff.T0.value, "S6"),
            (Tariff.T1.value, "S6"),
            (Tariff.T2.value, "S5"),
        ):
            with self.subTest(tariff=tariff_value):
                with self.SessionLocal() as session:
                    db_profile = session.execute(select(UserProfile).where(UserProfile.user_id == 1)).scalar_one()
                    db_profile.personal_data_consent_accepted_at = None
                    db_profile.personal_data_consent_source = None
                    session.query(ReportJob).delete()
                    session.query(Order).delete()
                    if tariff_value == Tariff.T1.value:
                        order = Order(
                            user_id=1,
                            tariff=Tariff.T1,
                            amount=990.0,
                            provider=PaymentProvider.NONE,
                            status=OrderStatus.PAID,
                        )
                        session.add(order)
                        session.flush()
                        state_data = {
                            "selected_tariff": tariff_value,
                            "order_id": str(order.id),
                        }
                    else:
                        state_data = {"selected_tariff": tariff_value}
                    session.commit()

                def _update_state(_user_id: int, **kwargs):
                    if kwargs:
                        state_data.update(kwargs)
                    return SimpleNamespace(data=state_data.copy())

                with (
                    patch.object(profile.screen_manager, "update_state", side_effect=_update_state),
                    patch.object(profile.screen_manager, "send_ephemeral_message", new=AsyncMock()) as send_ephemeral,
                    patch.object(profile.screen_manager, "show_screen", new=AsyncMock()) as show_screen,
                ):
                    callback.answer.reset_mock()
                    await profile.accept_profile_consent(callback)

                with self.SessionLocal() as session:
                    db_profile = session.execute(select(UserProfile).where(UserProfile.user_id == 1)).scalar_one()
                    self.assertIsNotNone(db_profile.personal_data_consent_accepted_at)
                    self.assertEqual(db_profile.personal_data_consent_source, "profile_flow")
                    self.assertIsNotNone(db_profile.marketing_consent_accepted_at)
                    self.assertIsNone(db_profile.marketing_consent_revoked_at)
                    self.assertEqual(db_profile.marketing_consent_source, "profile_flow")
                    events = session.execute(
                        select(MarketingConsentEvent).order_by(MarketingConsentEvent.id)
                    ).scalars().all()
                    self.assertEqual(events[-1].event_type, MarketingConsentEventType.ACCEPTED)
                    active_jobs = session.execute(
                        select(ReportJob).where(ReportJob.user_id == 1)
                    ).scalars().all()

                if tariff_value in {Tariff.T0.value, Tariff.T1.value}:
                    self.assertEqual(len(active_jobs), 1)
                    self.assertEqual(active_jobs[0].tariff.value, tariff_value)
                    self.assertEqual(active_jobs[0].status, ReportJobStatus.PENDING)
                else:
                    self.assertEqual(active_jobs, [])

                send_ephemeral.assert_awaited_once()
                show_screen.assert_awaited_with(
                    bot=callback.bot,
                    chat_id=5001,
                    user_id=1001,
                    screen_id=expected_screen,
                )
                callback.answer.assert_awaited_once()

    async def test_accept_consent_handles_missing_state_snapshot_without_crash(self) -> None:
        callback = SimpleNamespace(
            bot=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id=5001), answer=AsyncMock()),
            from_user=SimpleNamespace(id=1001, username="tester"),
            answer=AsyncMock(),
        )

        with (
            patch.object(profile.screen_manager, "update_state", side_effect=[None, None, None]),
            patch.object(profile.screen_manager, "send_ephemeral_message", new=AsyncMock()) as send_ephemeral,
            patch.object(profile.screen_manager, "show_screen", new=AsyncMock()) as show_screen,
        ):
            await profile.accept_profile_consent(callback)

        with self.SessionLocal() as session:
            db_profile = session.execute(select(UserProfile).where(UserProfile.user_id == 1)).scalar_one()
            self.assertIsNotNone(db_profile.personal_data_consent_accepted_at)
            self.assertEqual(db_profile.personal_data_consent_source, "profile_flow")
            self.assertIsNotNone(db_profile.marketing_consent_accepted_at)
            self.assertIsNone(db_profile.marketing_consent_revoked_at)
            events = session.execute(
                select(MarketingConsentEvent).order_by(MarketingConsentEvent.id)
            ).scalars().all()
            self.assertEqual(events[-1].event_type, MarketingConsentEventType.ACCEPTED)
            jobs = session.execute(select(ReportJob).where(ReportJob.user_id == 1)).scalars().all()
            self.assertEqual(jobs, [])

        send_ephemeral.assert_awaited_once_with(
            callback.message,
            "Не удалось запустить генерацию отчёта. Попробуйте снова.",
            user_id=1001,
        )
        show_screen.assert_not_awaited()
        callback.answer.assert_awaited_once()


    async def test_accept_without_marketing_sets_mandatory_consent_and_revokes_marketing(self) -> None:
        callback = SimpleNamespace(
            bot=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id=5001), answer=AsyncMock()),
            from_user=SimpleNamespace(id=1001, username="tester"),
            answer=AsyncMock(),
        )
        state_data = {"selected_tariff": Tariff.T2.value}

        def _update_state(_user_id: int, **kwargs):
            if kwargs:
                state_data.update(kwargs)
            return SimpleNamespace(data=state_data.copy())

        with (
            patch.object(profile.screen_manager, "update_state", side_effect=_update_state),
            patch.object(profile.screen_manager, "send_ephemeral_message", new=AsyncMock()) as send_ephemeral,
            patch.object(profile.screen_manager, "show_screen", new=AsyncMock()) as show_screen,
        ):
            await profile.accept_profile_consent_without_marketing(callback)

        with self.SessionLocal() as session:
            db_profile = session.execute(select(UserProfile).where(UserProfile.user_id == 1)).scalar_one()
            self.assertIsNotNone(db_profile.personal_data_consent_accepted_at)
            self.assertEqual(db_profile.personal_data_consent_source, "profile_flow")
            self.assertIsNotNone(db_profile.marketing_consent_revoked_at)
            self.assertEqual(db_profile.marketing_consent_revoked_source, "profile_flow")
            events = session.execute(
                select(MarketingConsentEvent).order_by(MarketingConsentEvent.id)
            ).scalars().all()
            self.assertEqual(events[-1].event_type, MarketingConsentEventType.REVOKED)

        send_ephemeral.assert_awaited_once_with(
            callback.message,
            "Согласие подтверждено.",
            user_id=1001,
        )
        show_screen.assert_awaited_once_with(
            bot=callback.bot,
            chat_id=5001,
            user_id=1001,
            screen_id="S5",
        )
        callback.answer.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
