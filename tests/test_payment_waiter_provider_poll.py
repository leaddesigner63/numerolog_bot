import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.handlers import screen_manager as screen_manager_module
from app.bot.handlers import screens
from app.db.base import Base
from app.db.models import (
    Order,
    OrderStatus,
    PaymentConfirmationSource,
    PaymentProvider,
    ScreenStateRecord,
    Tariff,
    User,
)


class PaymentWaiterProviderPollTests(unittest.IsolatedAsyncioTestCase):
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

        self._old_get_session_screens = screens.get_session
        self._old_get_session_screen_manager = screen_manager_module.get_session
        screens.get_session = _test_get_session
        screen_manager_module.get_session = _test_get_session

        self._old_report_delay = screens.settings.report_delay_seconds

        with self.SessionLocal() as session:
            user = User(id=1, telegram_user_id=1001, telegram_username="tester")
            session.add(user)
            session.commit()

    def tearDown(self) -> None:
        screens.get_session = self._old_get_session_screens
        screen_manager_module.get_session = self._old_get_session_screen_manager
        screens.settings.report_delay_seconds = self._old_report_delay
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _create_order(self) -> int:
        with self.SessionLocal() as session:
            order = Order(
                user_id=1,
                tariff=Tariff.T1,
                amount=560,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.CREATED,
            )
            session.add(order)
            session.flush()
            order_id = order.id
            session.commit()
        return order_id

    def _create_screen_state(self, order_id: int) -> None:
        with self.SessionLocal() as session:
            session.add(
                ScreenStateRecord(
                    telegram_user_id=1001,
                    screen_id="S3",
                    message_ids=[],
                    user_message_ids=[],
                    data={"order_id": str(order_id), "selected_tariff": Tariff.T1.value},
                )
            )
            session.commit()

    async def test_successful_poll_marks_order_paid_and_runs_post_payment_flow(self) -> None:
        screens.settings.report_delay_seconds = 0
        order_id = self._create_order()
        self._create_screen_state(order_id)

        provider = MagicMock()
        provider.check_payment_status.return_value = SimpleNamespace(
            is_paid=True,
            provider_payment_id="provider-123",
        )

        def _set_profile(_session, telegram_user_id: int) -> None:
            screens.screen_manager.update_state(telegram_user_id, profile={"name": "User"})

        def _set_questionnaire(_session, telegram_user_id: int) -> None:
            screens.screen_manager.update_state(
                telegram_user_id,
                questionnaire={"status": "completed"},
            )

        with (
            patch.object(screens, "get_payment_provider", return_value=provider),
            patch.object(screens.screen_manager, "show_screen", new=AsyncMock()) as show_screen,
            patch.object(screens, "_create_report_job", new=MagicMock()) as create_report_job,
            patch.object(screens, "_refresh_profile_state", side_effect=_set_profile),
            patch.object(screens, "_refresh_questionnaire_state", side_effect=_set_questionnaire),
        ):
            await screens._run_payment_waiter(bot=SimpleNamespace(), chat_id=1001, user_id=1001)

        with self.SessionLocal() as session:
            order = session.get(Order, order_id)
            self.assertIsNotNone(order)
            assert order is not None
            self.assertEqual(order.status, OrderStatus.PAID)
            self.assertTrue(order.payment_confirmed)
            self.assertIsNotNone(order.paid_at)
            self.assertIsNotNone(order.payment_confirmed_at)
            self.assertEqual(order.payment_confirmation_source, PaymentConfirmationSource.PROVIDER_POLL)
            self.assertEqual(order.provider_payment_id, "provider-123")

        show_screen.assert_awaited_once()
        self.assertEqual(show_screen.await_args.kwargs["screen_id"], "S6")
        self.assertEqual(show_screen.await_args.kwargs["trigger_value"], "payment_confirmed")
        create_report_job.assert_called_once()

    async def test_poll_none_keeps_user_on_s3(self) -> None:
        screens.settings.report_delay_seconds = 0
        order_id = self._create_order()
        self._create_screen_state(order_id)

        provider = MagicMock()
        provider.check_payment_status.return_value = None

        with (
            patch.object(screens, "get_payment_provider", return_value=provider),
            patch.object(screens.screen_manager, "show_screen", new=AsyncMock()) as show_screen,
            patch.object(screens.asyncio, "sleep", new=AsyncMock(side_effect=RuntimeError("stop"))),
        ):
            with self.assertRaises(RuntimeError):
                await screens._run_payment_waiter(
                    bot=SimpleNamespace(),
                    chat_id=1001,
                    user_id=1001,
                )

        with self.SessionLocal() as session:
            order = session.get(Order, order_id)
            state = session.get(ScreenStateRecord, 1001)
            self.assertIsNotNone(order)
            self.assertIsNotNone(state)
            assert order is not None
            assert state is not None
            self.assertEqual(order.status, OrderStatus.CREATED)
            self.assertEqual(state.screen_id, "S3")

        show_screen.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
