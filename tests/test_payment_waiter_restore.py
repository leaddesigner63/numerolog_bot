import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.handlers import screens
from app.bot.handlers import screen_manager as screen_manager_module
from app.db.base import Base
from app.db.models import Order, OrderStatus, PaymentProvider, ScreenStateRecord, Tariff, User


class PaymentWaiterRestoreTests(unittest.IsolatedAsyncioTestCase):
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

        with self.SessionLocal() as session:
            user = User(id=1, telegram_user_id=1001, telegram_username="tester")
            session.add(user)
            session.commit()

    def tearDown(self) -> None:
        screens.get_session = self._old_get_session_screens
        screen_manager_module.get_session = self._old_get_session_screen_manager
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _create_order(self, status: OrderStatus) -> int:
        with self.SessionLocal() as session:
            order = Order(
                user_id=1,
                tariff=Tariff.T1,
                amount=560,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=status,
            )
            session.add(order)
            session.flush()
            order_id = order.id
            session.commit()
        return order_id

    def _create_screen_state(self, order_id: int, screen_id: str = "S3") -> None:
        with self.SessionLocal() as session:
            session.add(
                ScreenStateRecord(
                    telegram_user_id=1001,
                    screen_id=screen_id,
                    message_ids=[],
                    user_message_ids=[],
                    data={"order_id": str(order_id)},
                )
            )
            session.commit()

    async def test_restore_payment_waiters_resumes_pending_order(self) -> None:
        order_id = self._create_order(OrderStatus.CREATED)
        self._create_screen_state(order_id)

        with patch.object(screens, "ensure_payment_waiter", new=AsyncMock()) as ensure_waiter:
            restored = await screens.restore_payment_waiters(SimpleNamespace())

        self.assertEqual(restored, 1)
        ensure_waiter.assert_awaited_once_with(bot=unittest.mock.ANY, chat_id=1001, user_id=1001)

    async def test_restore_payment_waiters_skips_paid_order(self) -> None:
        order_id = self._create_order(OrderStatus.PAID)
        self._create_screen_state(order_id)

        with patch.object(screens, "ensure_payment_waiter", new=AsyncMock()) as ensure_waiter:
            restored = await screens.restore_payment_waiters(SimpleNamespace())

        self.assertEqual(restored, 0)
        ensure_waiter.assert_not_awaited()

    async def test_restore_payment_waiters_ignores_non_checkout_screens(self) -> None:
        order_id = self._create_order(OrderStatus.CREATED)
        self._create_screen_state(order_id, screen_id="S4")

        with patch.object(screens, "ensure_payment_waiter", new=AsyncMock()) as ensure_waiter:
            restored = await screens.restore_payment_waiters(SimpleNamespace())

        self.assertEqual(restored, 0)
        ensure_waiter.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
