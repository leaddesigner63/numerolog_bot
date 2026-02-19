import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.handlers import start as start_module
from app.bot.handlers import screen_manager as screen_manager_module
from app.services import traffic_attribution as traffic_attribution_module
from app.bot.handlers.screen_manager import screen_manager
from app.db.base import Base
from app.db.models import (
    Order,
    OrderStatus,
    PaymentProvider,
    ReportJob,
    ReportJobStatus,
    Tariff,
    User,
    UserFirstTouchAttribution,
)


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
        self._old_traffic_get_session = traffic_attribution_module.get_session
        start_module.get_session = _test_get_session
        screen_manager_module.get_session = _test_get_session
        traffic_attribution_module.get_session = _test_get_session
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
        traffic_attribution_module.get_session = self._old_traffic_get_session
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

    def _create_report_job(self, user_id: int, order_id: int, status: ReportJobStatus) -> int:
        with self.SessionLocal() as session:
            job = ReportJob(
                user_id=user_id,
                order_id=order_id,
                tariff=Tariff.T2,
                status=status,
                attempts=0,
            )
            session.add(job)
            session.flush()
            job_id = job.id
            session.commit()
        return job_id


    def _first_touch_records(self, user_id: int = 1001) -> list[UserFirstTouchAttribution]:
        with self.SessionLocal() as session:
            return list(
                session.query(UserFirstTouchAttribution)
                .filter(UserFirstTouchAttribution.telegram_user_id == user_id)
                .all()
            )

    def _message(self, text: str, user_id: int = 1001):
        return SimpleNamespace(
            text=text,
            bot=SimpleNamespace(),
            chat=SimpleNamespace(id=5001),
            from_user=SimpleNamespace(id=user_id),
        )

    async def test_start_routes_to_s3_for_existing_unpaid_order(self) -> None:
        order_id = self._create_order(1, OrderStatus.CREATED)

        with (
            patch.object(screen_manager, "show_screen", new=AsyncMock()) as show_screen,
            patch.object(start_module, "ensure_payment_waiter", new=AsyncMock()) as ensure_waiter,
        ):
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
        ensure_waiter.assert_awaited_once()

    async def test_start_routes_to_s6_when_order_is_paid_but_report_not_completed(self) -> None:
        order_id = self._create_order(1, OrderStatus.PAID)
        self._create_report_job(1, order_id, ReportJobStatus.PENDING)

        with patch.object(screen_manager, "show_screen", new=AsyncMock()) as show_screen:
            await start_module.handle_start(self._message(f"/start paywait_{order_id}"))

        self.assertEqual(show_screen.await_args.kwargs["screen_id"], "S6")
        snapshot = screen_manager.update_state(1001)
        self.assertFalse(snapshot.data.get("s4_no_inline_keyboard"))
        self.assertEqual(snapshot.data.get("profile_flow"), "report")
        self.assertFalse(snapshot.data.get("payment_processing_notice"))

    async def test_start_routes_to_s7_when_order_is_paid_and_report_completed(self) -> None:
        order_id = self._create_order(1, OrderStatus.PAID)
        self._create_report_job(1, order_id, ReportJobStatus.COMPLETED)

        with patch.object(screen_manager, "show_screen", new=AsyncMock()) as show_screen:
            await start_module.handle_start(self._message(f"/start paywait_{order_id}"))

        self.assertEqual(show_screen.await_args.kwargs["screen_id"], "S7")

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

    async def test_start_shows_s0_without_payload_even_with_paid_order(self) -> None:
        self._create_order(1, OrderStatus.PAID)

        with patch.object(screen_manager, "show_screen", new=AsyncMock()) as show_screen:
            await start_module.handle_start(self._message("/start"))

        self.assertEqual(show_screen.await_args.kwargs["screen_id"], "S0")
        snapshot = screen_manager.update_state(1001)
        self.assertIsNone(snapshot.data.get("order_id"))
        self.assertIsNone(snapshot.data.get("selected_tariff"))
        self.assertFalse(snapshot.data.get("payment_processing_notice"))


    async def test_start_captures_first_touch_with_partial_payload_without_failures(self) -> None:
        with patch.object(screen_manager, "show_screen", new=AsyncMock()):
            await start_module.handle_start(self._message("/start source_only"))

        records = self._first_touch_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].start_payload, "source_only")
        self.assertEqual(records[0].source, "source")
        self.assertEqual(records[0].campaign, "only")
        self.assertIsNone(records[0].placement)
        self.assertEqual(records[0].raw_parts, ["source", "only"])


    async def test_start_captures_structured_lnd_payload(self) -> None:
        with patch.object(screen_manager, "show_screen", new=AsyncMock()):
            await start_module.handle_start(self._message("/start lnd.src_vkcmp_winterpl_banner_top"))

        records = self._first_touch_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].start_payload, "lnd.src_vkcmp_winterpl_banner_top")
        self.assertEqual(records[0].source, "vk")
        self.assertEqual(records[0].campaign, "winter")
        self.assertEqual(records[0].placement, "banner_top")

    async def test_start_first_touch_is_recorded_only_once_per_user(self) -> None:
        with patch.object(screen_manager, "show_screen", new=AsyncMock()):
            await start_module.handle_start(self._message("/start alpha_beta"))
            await start_module.handle_start(self._message("/start gamma_delta"))

        records = self._first_touch_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].start_payload, "alpha_beta")

    async def test_start_captures_empty_payload_with_safe_defaults(self) -> None:
        with patch.object(screen_manager, "show_screen", new=AsyncMock()):
            await start_module.handle_start(self._message("/start"))

        records = self._first_touch_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].start_payload, "")
        self.assertIsNone(records[0].source)
        self.assertIsNone(records[0].campaign)
        self.assertIsNone(records[0].placement)
        self.assertEqual(records[0].raw_parts, [])

    async def test_start_ignores_paid_history_without_payload(self) -> None:
        self._create_order(1, OrderStatus.PAID)

        with patch.object(screen_manager, "show_screen", new=AsyncMock()) as show_screen:
            await start_module.handle_start(self._message("/start"))

        self.assertEqual(show_screen.await_args.kwargs["screen_id"], "S0")


if __name__ == "__main__":
    unittest.main()
