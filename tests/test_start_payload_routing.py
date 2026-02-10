import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.handlers import start as start_module
from app.bot.handlers import screen_manager as screen_manager_module
from app.bot.handlers.screen_manager import screen_manager
from app.db.base import Base
from app.db.models import Order, OrderStatus, PaymentProvider, Tariff, User


class StartPayloadRoutingTests(unittest.IsolatedAsyncioTestCase):
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

        self._old_get_session = start_module.get_session
        self._old_screen_manager_get_session = screen_manager_module.get_session
        start_module.get_session = _test_get_session
        screen_manager_module.get_session = _test_get_session
        screen_manager._store._states.clear()

        with self.SessionLocal() as session:
            session.add_all(
                [
                    User(id=1, telegram_user_id=1001, telegram_username="owner"),
                    User(id=2, telegram_user_id=2002, telegram_username="other"),
                ]
            )
            session.commit()

    def tearDown(self) -> None:
        start_module.get_session = self._old_get_session
        screen_manager_module.get_session = self._old_screen_manager_get_session
        screen_manager._store._states.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _create_order(self, user_id: int, status: OrderStatus) -> int:
        with self.SessionLocal() as session:
            order = Order(
                user_id=user_id,
                tariff=Tariff.T2,
                amount=790,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=status,
            )
            session.add(order)
            session.flush()
            order_id = order.id
            session.commit()
        return order_id

    def _message(self, text: str, user_id: int = 1001):
        return SimpleNamespace(
            text=text,
            bot=SimpleNamespace(),
            chat=SimpleNamespace(id=5001),
            from_user=SimpleNamespace(id=user_id),
        )

    async def test_start_routes_to_s3_for_existing_unpaid_order(self) -> None:
        order_id = self._create_order(1, OrderStatus.CREATED)

        with patch.object(screen_manager, "show_screen", new=AsyncMock()) as show_screen:
            await start_module.handle_start(self._message(f"/start paywait_{order_id}"))

        show_screen.assert_awaited_with(
            bot=unittest.mock.ANY,
            chat_id=5001,
            user_id=1001,
            screen_id="S3",
            trigger_type="message",
            trigger_value=f"command:/start payload:paywait_{order_id}",
        )
        snapshot = screen_manager.update_state(1001)
        self.assertEqual(snapshot.data.get("order_id"), str(order_id))
        self.assertEqual(snapshot.data.get("order_status"), OrderStatus.CREATED.value)
        self.assertEqual(snapshot.data.get("selected_tariff"), Tariff.T2.value)
        self.assertTrue(snapshot.data.get("payment_processing_notice"))

    async def test_start_routes_to_s4_when_order_is_paid(self) -> None:
        order_id = self._create_order(1, OrderStatus.PAID)

        with patch.object(screen_manager, "show_screen", new=AsyncMock()) as show_screen:
            await start_module.handle_start(self._message(f"/start paywait_{order_id}"))

        self.assertEqual(show_screen.await_args.kwargs["screen_id"], "S4")
        snapshot = screen_manager.update_state(1001)
        self.assertTrue(snapshot.data.get("s4_no_inline_keyboard"))
        self.assertFalse(snapshot.data.get("payment_processing_notice"))

    async def test_start_falls_back_to_s0_for_foreign_order(self) -> None:
        order_id = self._create_order(2, OrderStatus.CREATED)

        with patch.object(screen_manager, "show_screen", new=AsyncMock()) as show_screen:
            await start_module.handle_start(self._message(f"/start paywait_{order_id}"))

        self.assertEqual(show_screen.await_args.kwargs["screen_id"], "S0")
        snapshot = screen_manager.update_state(1001)
        self.assertFalse(snapshot.data.get("s4_no_inline_keyboard"))

    async def test_start_falls_back_to_s0_for_invalid_payload(self) -> None:
        with patch.object(screen_manager, "show_screen", new=AsyncMock()) as show_screen:
            await start_module.handle_start(self._message("/start paywait_not_a_number"))

        self.assertEqual(show_screen.await_args.kwargs["screen_id"], "S0")
        snapshot = screen_manager.update_state(1001)
        self.assertFalse(snapshot.data.get("s4_no_inline_keyboard"))


if __name__ == "__main__":
    unittest.main()
