import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.handlers import screen_manager as screen_manager_module
from app.bot.handlers import screens
from app.db.base import Base
from app.db.models import Order, OrderStatus, PaymentProvider, Report, ReportJob, Tariff, User, UserProfile


class _DummyCallback:
    def __init__(self, data: str, user_id: int = 1001) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id, username="tester")
        self.message = SimpleNamespace(chat=SimpleNamespace(id=5001), message_id=7001)
        self.bot = SimpleNamespace()
        self.answered = False

    async def answer(self, *_args, **_kwargs):
        self.answered = True


class PaymentScreenTransitionsTests(unittest.IsolatedAsyncioTestCase):
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

        self._test_get_session = _test_get_session

        self._old_get_session_screens = screens.get_session
        self._old_get_session_screen_manager = screen_manager_module.get_session
        screens.get_session = _test_get_session
        screen_manager_module.get_session = _test_get_session

        screens.screen_manager._store._states.clear()

        with self.SessionLocal() as session:
            user = User(id=1, telegram_user_id=1001, telegram_username="tester")
            session.add(user)
            session.commit()

    def tearDown(self) -> None:
        screens.get_session = self._old_get_session_screens
        screen_manager_module.get_session = self._old_get_session_screen_manager
        screens.screen_manager._store._states.clear()
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


    def _create_profile(self) -> None:
        with self.SessionLocal() as session:
            profile = UserProfile(
                user_id=1,
                name="Иван",
                birth_date="2000-01-01",
                birth_time="10:00",
                birth_place_city="Москва",
                birth_place_region="Московская область",
                birth_place_country="Россия",
            )
            session.add(profile)
            session.commit()

    async def test_profile_save_blocks_report_generation_until_paid(self) -> None:
        order_id = self._create_order(OrderStatus.CREATED)
        self._create_profile()
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            order_id=str(order_id),
        )
        callback = _DummyCallback("profile:save")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_send_notice", new=AsyncMock()) as send_notice,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S3")
        send_notice.assert_awaited()
        with self.SessionLocal() as session:
            jobs_count = session.execute(select(func.count(ReportJob.id))).scalar_one()
        self.assertEqual(jobs_count, 0)

    async def test_s3_auto_redirects_to_profile_when_order_already_paid(self) -> None:
        order_id = self._create_order(OrderStatus.PAID)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            order_id=str(order_id),
            order_status=OrderStatus.PAID.value,
            offer_seen=True,
        )
        callback = _DummyCallback("screen:S3")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S4")
        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertEqual(state_snapshot.data.get("profile_flow"), "report")

    async def test_profile_save_reuses_existing_report_for_paid_order(self) -> None:
        order_id = self._create_order(OrderStatus.PAID)
        with self.SessionLocal() as session:
            session.add(
                Report(
                    user_id=1,
                    order_id=order_id,
                    tariff=Tariff.T1,
                    report_text="Готовый отчёт",
                )
            )
            session.commit()

        self._create_profile()
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            order_id=str(order_id),
        )
        callback = _DummyCallback("profile:save")

        with (
            patch.object(screens, "_ensure_report_delivery", new=AsyncMock(return_value=True)) as ensure_delivery,
            patch.object(screens, "_send_report_pdf", new=AsyncMock(return_value=True)),
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        ensure_delivery.assert_awaited_with(callback, "S7")
        with self.SessionLocal() as session:
            jobs_count = session.execute(select(func.count(ReportJob.id))).scalar_one()
        self.assertEqual(jobs_count, 0)

    async def test_report_retry_requires_confirmed_payment(self) -> None:
        order_id = self._create_order(OrderStatus.CREATED)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            order_id=str(order_id),
        )
        callback = _DummyCallback("report:retry")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_send_notice", new=AsyncMock()) as send_notice,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S3")
        send_notice.assert_awaited()


    async def test_tariff_with_existing_report_opens_warning_without_creating_order(self) -> None:
        paid_order_id = self._create_order(OrderStatus.PAID)
        with self.SessionLocal() as session:
            session.add(
                Report(
                    user_id=1,
                    order_id=paid_order_id,
                    tariff=Tariff.T1,
                    report_text="Существующий отчёт",
                )
            )
            session.commit()
            before_orders_count = session.execute(select(func.count(Order.id))).scalar_one()

        callback = _DummyCallback("tariff:T1")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S2")
        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertTrue(state_snapshot.data.get("existing_tariff_report_found"))
        self.assertEqual(state_snapshot.data.get("selected_tariff"), Tariff.T1.value)
        self.assertFalse(state_snapshot.data.get("existing_report_warning_seen"))

        with self.SessionLocal() as session:
            after_orders_count = session.execute(select(func.count(Order.id))).scalar_one()
        self.assertEqual(after_orders_count, before_orders_count)

    async def test_tariff_without_reports_opens_offer_without_order(self) -> None:
        with self.SessionLocal() as session:
            before_orders_count = session.execute(select(func.count(Order.id))).scalar_one()

        callback = _DummyCallback("tariff:T2")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S2")
        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertEqual(state_snapshot.data.get("selected_tariff"), Tariff.T2.value)
        self.assertEqual(state_snapshot.data.get("reports_total"), 0)
        self.assertEqual(state_snapshot.data.get("reports"), [])
        self.assertFalse(state_snapshot.data.get("existing_tariff_report_found"))
        self.assertFalse(state_snapshot.data.get("existing_report_warning_seen"))

        with self.SessionLocal() as session:
            after_orders_count = session.execute(select(func.count(Order.id))).scalar_one()
        self.assertEqual(after_orders_count, before_orders_count)

    async def test_questionnaire_done_resets_stale_failed_status_before_wait_screen(self) -> None:
        order_id = self._create_order(OrderStatus.PAID)
        with self.SessionLocal() as session:
            failed_job = ReportJob(
                user_id=1,
                order_id=None,
                tariff=Tariff.T0,
                status=screens.ReportJobStatus.FAILED,
                attempts=1,
            )
            session.add(failed_job)
            session.flush()
            failed_job_id = failed_job.id
            session.commit()

        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T2.value,
            order_id=str(order_id),
            report_job_id=str(failed_job_id),
            report_job_status=screens.ReportJobStatus.FAILED.value,
            questionnaire={"status": "completed"},
        )
        callback = _DummyCallback("questionnaire:done")

        observed_status = {}

        async def _show_screen_side_effect(_callback, *, screen_id):
            if screen_id == "S6":
                state_snapshot = screens.screen_manager.update_state(1001)
                observed_status["status"] = state_snapshot.data.get("report_job_status")
            return True

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock(side_effect=_show_screen_side_effect)) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
            patch.object(screens, "_maybe_run_report_delay", new=AsyncMock()),
            patch.object(screens, "_send_notice", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S6")
        self.assertEqual(observed_status.get("status"), screens.ReportJobStatus.PENDING.value)
        with self.SessionLocal() as session:
            pending_jobs = (
                session.execute(
                    select(func.count(ReportJob.id)).where(
                        ReportJob.user_id == 1,
                        ReportJob.tariff == Tariff.T2,
                        ReportJob.order_id == order_id,
                        ReportJob.status == screens.ReportJobStatus.PENDING,
                    )
                ).scalar_one()
            )
        self.assertEqual(pending_jobs, 1)

    async def test_existing_report_lk_opens_personal_account_screen(self) -> None:
        callback = _DummyCallback("existing_report:lk")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S11")

    async def test_existing_report_continue_creates_new_order_and_returns_to_payment(self) -> None:
        paid_order_id = self._create_order(OrderStatus.PAID)
        with self.SessionLocal() as session:
            session.add(
                Report(
                    user_id=1,
                    order_id=paid_order_id,
                    tariff=Tariff.T1,
                    report_text="Существующий отчёт",
                )
            )
            session.commit()
            before_orders_count = session.execute(select(func.count(Order.id))).scalar_one()

        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            existing_tariff_report_found=True,
            existing_tariff_report_meta={"id": "1", "tariff": Tariff.T1.value, "created_at": "2025-01-01"},
        )

        callback = _DummyCallback("existing_report:continue")

        with (
            patch.object(screens.settings, "payment_enabled", False),
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S3")

        with self.SessionLocal() as session:
            after_orders_count = session.execute(select(func.count(Order.id))).scalar_one()
            latest_order = session.execute(select(Order).order_by(Order.id.desc()).limit(1)).scalar_one()

        self.assertEqual(after_orders_count, before_orders_count + 1)
        self.assertEqual(latest_order.tariff, Tariff.T1)
        self.assertEqual(latest_order.status, OrderStatus.CREATED)

        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertEqual(state_snapshot.data.get("order_id"), str(latest_order.id))
        self.assertFalse(state_snapshot.data.get("existing_tariff_report_found"))
        self.assertTrue(state_snapshot.data.get("existing_report_warning_seen"))

    async def test_s3_opens_existing_report_warning_after_offer_screen(self) -> None:
        order_id = self._create_order(OrderStatus.CREATED)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            order_id=str(order_id),
            offer_seen=True,
            existing_tariff_report_found=True,
            existing_report_warning_seen=False,
        )
        callback = _DummyCallback("screen:S3")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S15")


if __name__ == "__main__":
    unittest.main()
