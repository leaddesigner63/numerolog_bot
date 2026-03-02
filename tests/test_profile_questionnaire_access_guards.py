import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.handlers import screen_manager as screen_manager_module
from app.bot.handlers import profile, questionnaire, tariff_context
from app.db.base import Base
from app.db.models import Order, OrderStatus, PaymentProvider, Tariff, User


class ProfileQuestionnaireAccessGuardsTests(unittest.IsolatedAsyncioTestCase):
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

        self._old_get_session_questionnaire = questionnaire.get_session
        self._old_get_session_profile = profile.get_session
        self._old_get_session_screen_manager = screen_manager_module.get_session
        self._old_get_session_tariff_context = tariff_context.get_session

        questionnaire.get_session = _test_get_session
        profile.get_session = _test_get_session
        screen_manager_module.get_session = _test_get_session
        tariff_context.get_session = _test_get_session

        questionnaire.screen_manager._store._states.clear()

        with self.SessionLocal() as session:
            session.add(User(id=1, telegram_user_id=101, telegram_username="tester"))
            session.commit()

    def tearDown(self) -> None:
        questionnaire.get_session = self._old_get_session_questionnaire
        profile.get_session = self._old_get_session_profile
        screen_manager_module.get_session = self._old_get_session_screen_manager
        tariff_context.get_session = self._old_get_session_tariff_context
        questionnaire.screen_manager._store._states.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _create_order(self, tariff: Tariff) -> None:
        with self.SessionLocal() as session:
            session.add(
                Order(
                    user_id=1,
                    tariff=tariff,
                    amount=1200,
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.CREATED,
                )
            )
            session.commit()

    async def test_profile_access_for_paid_tariff_does_not_require_paid_order(self) -> None:
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=101),
            message=SimpleNamespace(chat=SimpleNamespace(id=202)),
            bot=AsyncMock(),
        )
        state_snapshot = SimpleNamespace(data={"selected_tariff": Tariff.T1.value})

        with (
            patch.object(profile.screen_manager, "update_state", return_value=state_snapshot),
            patch.object(profile.screen_manager, "send_ephemeral_message", new=AsyncMock()) as send_ephemeral,
            patch.object(profile.screen_manager, "show_screen", new=AsyncMock()) as show_screen,
        ):
            allowed = await profile._ensure_profile_access(callback)

        self.assertTrue(allowed)
        send_ephemeral.assert_not_awaited()
        show_screen.assert_not_awaited()

    async def test_questionnaire_access_for_t2_does_not_require_paid_order(self) -> None:
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=101),
            message=SimpleNamespace(chat=SimpleNamespace(id=202)),
            bot=AsyncMock(),
        )
        state_snapshot = SimpleNamespace(data={"selected_tariff": Tariff.T2.value})

        with (
            patch.object(questionnaire.screen_manager, "update_state", return_value=state_snapshot),
            patch.object(questionnaire.screen_manager, "send_ephemeral_message", new=AsyncMock()) as send_ephemeral,
            patch.object(questionnaire.screen_manager, "show_screen", new=AsyncMock()) as show_screen,
        ):
            allowed = await questionnaire._ensure_questionnaire_access(callback)

        self.assertTrue(allowed)
        send_ephemeral.assert_not_awaited()
        show_screen.assert_not_awaited()

    async def test_questionnaire_access_blocks_non_t2_t3_tariff(self) -> None:
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=101),
            message=SimpleNamespace(chat=SimpleNamespace(id=202)),
            bot=AsyncMock(),
        )
        state_snapshot = SimpleNamespace(data={"selected_tariff": Tariff.T1.value})

        with (
            patch.object(questionnaire.screen_manager, "update_state", return_value=state_snapshot),
            patch.object(questionnaire.screen_manager, "send_ephemeral_message", new=AsyncMock()) as send_ephemeral,
            patch.object(questionnaire.screen_manager, "show_screen", new=AsyncMock()) as show_screen,
        ):
            allowed = await questionnaire._ensure_questionnaire_access(callback)

        self.assertFalse(allowed)
        send_ephemeral.assert_awaited_once()
        show_screen.assert_awaited_once()

    async def test_questionnaire_access_restores_tariff_from_db_when_state_missing(self) -> None:
        self._create_order(Tariff.T3)
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=101),
            message=SimpleNamespace(chat=SimpleNamespace(id=202)),
            bot=AsyncMock(),
        )
        with (
            patch.object(questionnaire.screen_manager, "send_ephemeral_message", new=AsyncMock()) as send_ephemeral,
            patch.object(questionnaire.screen_manager, "show_screen", new=AsyncMock()) as show_screen,
        ):
            questionnaire.screen_manager.update_state(101, selected_tariff=None)
            allowed = await questionnaire._ensure_questionnaire_access(callback)

        self.assertTrue(allowed)
        self.assertEqual(
            questionnaire.screen_manager.update_state(101).data.get("selected_tariff"),
            Tariff.T3.value,
        )
        send_ephemeral.assert_not_awaited()
        show_screen.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
