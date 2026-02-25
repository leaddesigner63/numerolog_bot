import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, inspect, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.handlers import screen_manager as screen_manager_module
from app.bot.handlers import screens
from app.db.base import Base
from app.db.models import (
    Order,
    OrderFulfillmentStatus,
    OrderStatus,
    PaymentProvider,
    Report,
    ReportJob,
    Tariff,
    User,
    UserProfile,
)


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

    def _create_order(self, status: OrderStatus, tariff: Tariff = Tariff.T1) -> int:
        with self.SessionLocal() as session:
            order = Order(
                user_id=1,
                tariff=tariff,
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


    def _create_profile(self, consent_accepted: bool = False) -> None:
        with self.SessionLocal() as session:
            profile = UserProfile(
                user_id=1,
                name="Иван",
                birth_date="2000-01-01",
                birth_time="10:00",
                birth_place_city="Москва",
                birth_place_region="Московская область",
                birth_place_country="Россия",
                personal_data_consent_accepted_at=(
                    screens.now_app_timezone() if consent_accepted else None
                ),
                personal_data_consent_source=("profile_flow" if consent_accepted else None),
            )
            session.add(profile)
            session.commit()

    async def test_profile_save_routes_to_s3_for_t1_with_created_order(self) -> None:
        self._create_profile(consent_accepted=True)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            order_id="777",
            order_status=OrderStatus.CREATED.value,
            payment_url="https://old.example/pay",
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
        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertIsNotNone(state_snapshot.data.get("order_id"))
        self.assertEqual(state_snapshot.data.get("s3_back_target"), "S4")

    async def test_open_checkout_s3_sets_default_back_target_for_t1(self) -> None:
        callback = _DummyCallback("screen:S3")
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            order_id="777",
        )

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_maybe_run_payment_waiter", new=AsyncMock()),
        ):
            opened = await screens.open_checkout_s3_with_order(callback)

        self.assertTrue(opened)
        show_screen.assert_awaited_once_with(callback, screen_id="S3")
        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertEqual(state_snapshot.data.get("s3_back_target"), "S4")

    async def test_open_checkout_s3_honors_explicit_back_target(self) -> None:
        callback = _DummyCallback("screen:S3")
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T2.value,
            order_id="778",
        )

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_maybe_run_payment_waiter", new=AsyncMock()),
        ):
            opened = await screens.open_checkout_s3_with_order(
                callback,
                fallback_screen_id="S5",
            )

        self.assertTrue(opened)
        show_screen.assert_awaited_once_with(callback, screen_id="S3")
        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertEqual(state_snapshot.data.get("s3_back_target"), "S5")

    async def test_profile_save_requires_personal_data_consent(self) -> None:
        order_id = self._create_order(OrderStatus.PAID, tariff=Tariff.T2)
        self._create_profile(consent_accepted=False)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T2.value,
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

        show_screen.assert_awaited_with(callback, screen_id="S4_CONSENT")
        send_notice.assert_awaited()
        with self.SessionLocal() as session:
            jobs_count = session.execute(select(func.count(ReportJob.id))).scalar_one()
        self.assertEqual(jobs_count, 0)

    async def test_s3_requires_profile_before_checkout(self) -> None:
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
            patch.object(screens, "start_profile_wizard", new=AsyncMock()),
            patch.object(screens, "_send_notice", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=AsyncMock())

        show_screen.assert_awaited_with(callback, screen_id="S4")

    async def test_s3_paid_order_with_profile_skips_repeated_checkout_screen(self) -> None:
        order_id = self._create_order(OrderStatus.PAID)
        self._create_profile(consent_accepted=True)
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
            patch.object(screens, "_maybe_run_payment_waiter", new=AsyncMock()) as run_waiter,
            patch.object(screens, "_send_notice", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=AsyncMock())

        show_screen.assert_awaited_once_with(callback, screen_id="S4")
        run_waiter.assert_not_awaited()

    async def test_profile_save_generates_report_for_paid_t1_order(self) -> None:
        order_id = self._create_order(OrderStatus.PAID)
        self._create_profile(consent_accepted=True)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            order_id=str(order_id),
            profile_flow="report",
        )
        callback = _DummyCallback("profile:save")

        with (
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_maybe_run_report_delay", new=AsyncMock()) as report_delay,
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S6")
        report_delay.assert_awaited_once()
        with self.SessionLocal() as session:
            jobs_count = session.execute(select(func.count(ReportJob.id))).scalar_one()
            job = session.execute(select(ReportJob).order_by(ReportJob.id.desc())).scalar_one()
        self.assertEqual(jobs_count, 1)
        self.assertEqual(job.order_id, order_id)

    async def test_profile_save_t1_with_unpaid_order_routes_to_s3_with_order_id(self) -> None:
        self._create_profile(consent_accepted=True)
        for status in (OrderStatus.CREATED, OrderStatus.PENDING):
            with self.subTest(status=status.value):
                order_id = self._create_order(status)
                screens.screen_manager._store._states.clear()
                screens.screen_manager.update_state(
                    1001,
                    selected_tariff=Tariff.T1.value,
                    order_id=str(order_id),
                )
                callback = _DummyCallback("profile:save")

                with (
                    patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
                    patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
                    patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
                    patch.object(screens, "_create_report_job", new=AsyncMock()) as create_job,
                    patch.object(screens, "_send_notice", new=AsyncMock()),
                ):
                    await screens.handle_callbacks(callback, state=SimpleNamespace())

                show_screen.assert_awaited_with(callback, screen_id="S3")
                create_job.assert_not_awaited()
                state_snapshot = screens.screen_manager.update_state(1001)
                self.assertIsNotNone(state_snapshot.data.get("order_id"))

    async def test_profile_save_t1_without_order_routes_to_s3_with_order_id(self) -> None:
        self._create_profile(consent_accepted=True)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            order_id=None,
        )
        callback = _DummyCallback("profile:save")

        with (
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_create_report_job", new=AsyncMock()) as create_job,
            patch.object(screens, "_send_notice", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S3")
        create_job.assert_not_awaited()
        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertIsNotNone(state_snapshot.data.get("order_id"))

    async def test_payment_start_creates_checkout_order_for_t1(self) -> None:
        self._create_profile(consent_accepted=True)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            order_id=None,
        )
        callback = _DummyCallback("payment:start")

        with (
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_prepare_checkout_order", new=AsyncMock(return_value=SimpleNamespace(id=999))) as prepare_checkout,
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        prepare_checkout.assert_awaited_once_with(callback, tariff_value=Tariff.T1.value)
        show_screen.assert_awaited_with(callback, screen_id="S3")

    async def test_payment_start_creates_checkout_order_for_t2_t3(self) -> None:
        self._create_profile(consent_accepted=True)
        for tariff in (Tariff.T2, Tariff.T3):
            with self.subTest(tariff=tariff.value):
                screens.screen_manager._store._states.clear()
                screens.screen_manager.update_state(
                    1001,
                    selected_tariff=tariff.value,
                    questionnaire={"status": "completed"},
                    personal_data_consent_accepted=True,
                )
                callback = _DummyCallback("payment:start")

                with (
                    patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
                    patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
                    patch.object(screens, "_refresh_questionnaire_state") as refresh_questionnaire,
                    patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
                    patch.object(
                        screens,
                        "_prepare_checkout_order",
                        new=AsyncMock(return_value=SimpleNamespace(id=999)),
                    ) as prepare_checkout,
                ):
                    refresh_questionnaire.return_value = None
                    await screens.handle_callbacks(callback, state=SimpleNamespace())

                prepare_checkout.assert_awaited_once_with(callback, tariff_value=tariff.value)
                show_screen.assert_awaited_with(callback, screen_id="S3")

    async def test_payment_start_for_t2_with_incomplete_questionnaire_returns_to_s5(self) -> None:
        self._create_profile(consent_accepted=True)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T2.value,
            questionnaire={"status": "in_progress"},
            personal_data_consent_accepted=True,
        )
        callback = _DummyCallback("payment:start")

        with (
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
            patch.object(screens, "_refresh_questionnaire_state") as refresh_questionnaire,
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_send_notice", new=AsyncMock()) as send_notice,
            patch.object(screens, "_prepare_checkout_order", new=AsyncMock()) as prepare_checkout,
        ):
            refresh_questionnaire.return_value = None
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        send_notice.assert_awaited_with(callback, "Сначала заполните анкету.")
        show_screen.assert_awaited_with(callback, screen_id="S5")
        prepare_checkout.assert_not_awaited()

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
        with self.SessionLocal() as session:
            jobs_count = session.execute(select(func.count(ReportJob.id))).scalar_one()
        self.assertEqual(jobs_count, 0)

    async def test_report_retry_paid_order_opens_wait_screen_and_creates_job(self) -> None:
        order_id = self._create_order(OrderStatus.PAID)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            order_id=str(order_id),
        )
        callback = _DummyCallback("report:retry")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
            patch.object(screens, "_maybe_run_report_delay", new=AsyncMock()) as report_delay,
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S6")
        report_delay.assert_awaited_once()
        with self.SessionLocal() as session:
            jobs_count = session.execute(select(func.count(ReportJob.id))).scalar_one()
            job = session.execute(select(ReportJob).order_by(ReportJob.id.desc())).scalar_one()
        self.assertEqual(jobs_count, 1)
        self.assertEqual(job.order_id, order_id)


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
            paid_order = session.get(Order, paid_order_id)
            if paid_order:
                paid_order.consumed_at = datetime.now(timezone.utc)
                session.add(paid_order)
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

    async def test_s2_details_opens_detailed_step_for_paid_tariff(self) -> None:
        screens.screen_manager.update_state(1001, selected_tariff=Tariff.T1.value)
        callback = _DummyCallback("s2:details")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S2_MORE")

    async def test_s2_details_back_returns_to_s2_without_losing_tariff(self) -> None:
        screens.screen_manager.update_state(1001, selected_tariff=Tariff.T3.value)
        callback = _DummyCallback("s2:details:back")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S2")
        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertEqual(state_snapshot.data.get("selected_tariff"), Tariff.T3.value)
        self.assertTrue(state_snapshot.data.get("offer_seen"))

    async def test_tariff_reuses_paid_unfulfilled_order_and_skips_payment_screen(self) -> None:
        with self.SessionLocal() as session:
            session.add(
                Order(
                    user_id=1,
                    tariff=Tariff.T2,
                    amount=2190,
                    currency="RUB",
                    provider=PaymentProvider.PRODAMUS,
                    status=OrderStatus.PAID,
                    fulfillment_status=OrderFulfillmentStatus.PENDING,
                )
            )
            session.commit()
            paid_order = session.execute(
                select(Order)
                .where(Order.user_id == 1, Order.tariff == Tariff.T2)
                .limit(1)
            ).scalar_one()

        callback = _DummyCallback("tariff:T2")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S4")
        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertEqual(state_snapshot.data.get("order_id"), str(paid_order.id))
        self.assertEqual(state_snapshot.data.get("order_status"), OrderStatus.PAID.value)
        self.assertTrue(state_snapshot.data.get("offer_seen"))
        self.assertEqual(state_snapshot.data.get("profile_flow"), "report")

    async def test_s3_requires_questionnaire_for_t3_before_checkout(self) -> None:
        order_id = self._create_order(OrderStatus.PENDING, tariff=Tariff.T3)

        self._create_profile(consent_accepted=True)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T3.value,
            order_id=str(order_id),
            offer_seen=True,
            profile={"name": "Иван"},
            questionnaire={"status": "in_progress"},
        )
        callback = _DummyCallback("screen:S3")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
            patch.object(screens, "_send_notice", new=AsyncMock()),
            patch.object(screens, "_maybe_run_payment_waiter", new=AsyncMock()) as maybe_run_payment_waiter,
        ):
            await screens.handle_callbacks(callback, state=AsyncMock())

        show_screen.assert_awaited_with(callback, screen_id="S5")
        maybe_run_payment_waiter.assert_not_awaited()

    async def test_s3_with_completed_questionnaire_for_t3_runs_payment_flow(self) -> None:
        order_id = self._create_order(OrderStatus.PENDING, tariff=Tariff.T3)
        self._create_profile(consent_accepted=True)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T3.value,
            order_id=str(order_id),
            offer_seen=True,
            profile={"name": "Иван"},
            questionnaire={"status": "completed"},
        )
        callback = _DummyCallback("screen:S3")

        with (
            patch.object(screens, "_show_marketing_consent_or_target_screen", new=AsyncMock()) as show_target_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
            patch.object(screens, "_send_notice", new=AsyncMock()) as send_notice,
            patch.object(screens, "_refresh_questionnaire_state") as refresh_questionnaire,
            patch.object(screens, "_maybe_run_payment_waiter", new=AsyncMock()) as maybe_run_payment_waiter,
        ):
            refresh_questionnaire.return_value = None
            await screens.handle_callbacks(callback, state=AsyncMock())

        show_target_screen.assert_awaited_with(callback, screen_id="S3")
        maybe_run_payment_waiter.assert_awaited_once_with(callback)
        send_notice.assert_not_awaited()

    async def test_s3_does_not_create_order_before_final_checkout_trigger(self) -> None:
        self._create_profile(consent_accepted=True)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            offer_seen=True,
            profile={"name": "Иван"},
        )
        with self.SessionLocal() as session:
            before_orders_count = session.execute(select(func.count(Order.id))).scalar_one()

        callback = _DummyCallback("screen:S3")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_send_notice", new=AsyncMock()) as send_notice,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
            patch.object(screens, "_maybe_run_payment_waiter", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=AsyncMock())

        show_screen.assert_awaited_with(callback, screen_id="S4")
        send_notice.assert_awaited()
        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertIsNone(state_snapshot.data.get("order_id"))
        with self.SessionLocal() as session:
            after_orders_count = session.execute(select(func.count(Order.id))).scalar_one()
        self.assertEqual(after_orders_count, before_orders_count)

    async def test_questionnaire_done_routes_to_checkout(self) -> None:
        self._create_profile(consent_accepted=True)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T2.value,
            questionnaire={"status": "completed"},
            personal_data_consent_accepted=True,
        )
        callback = _DummyCallback("questionnaire:done")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
            patch.object(screens, "_send_notice", new=AsyncMock()),
            patch.object(screens, "_refresh_questionnaire_state"),
            patch.object(screens, "_refresh_profile_state"),
        ):
            await screens.handle_callbacks(callback, state=AsyncMock())

        show_screen.assert_awaited_with(callback, screen_id="S3")
        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertIsNotNone(state_snapshot.data.get("order_id"))

    async def test_payment_start_shows_notice_when_payment_link_config_missing(self) -> None:
        self._create_profile(consent_accepted=True)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
        )
        callback = _DummyCallback("payment:start")

        with (
            patch.object(screens.settings, "payment_enabled", True),
            patch.object(screens.settings, "prodamus_form_url", ""),
            patch.object(screens.settings, "cloudpayments_public_id", ""),
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_send_notice", new=AsyncMock()) as send_notice,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S3")
        send_notice.assert_awaited()

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
            payment_processing_notice=True,
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
        self.assertFalse(state_snapshot.data.get("payment_processing_notice"))

    async def test_s3_opens_existing_report_warning_after_offer_screen(self) -> None:
        order_id = self._create_order(OrderStatus.CREATED)
        self._create_profile(consent_accepted=True)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            order_id=str(order_id),
            offer_seen=True,
            existing_tariff_report_found=True,
            existing_report_warning_seen=False,
            profile={"name": "Иван"},
        )
        callback = _DummyCallback("screen:S3")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=AsyncMock())

        show_screen.assert_awaited_with(callback, screen_id="S15")

    async def test_payment_start_opens_existing_report_warning_before_checkout(self) -> None:
        order_id = self._create_order(OrderStatus.CREATED)
        self._create_profile(consent_accepted=True)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            order_id=str(order_id),
            offer_seen=True,
            existing_tariff_report_found=True,
            existing_report_warning_seen=False,
            personal_data_consent_accepted=True,
            profile={"name": "Иван"},
        )
        callback = _DummyCallback("payment:start")

        with (
            patch.object(screens, "_prepare_checkout_order", new=AsyncMock(return_value=SimpleNamespace(id=order_id))),
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S15")


    async def test_s3_report_details_navigation_keeps_order_state(self) -> None:
        order_id = self._create_order(OrderStatus.CREATED)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T3.value,
            order_id=str(order_id),
        )

        with (
            patch.object(screens, "_prepare_checkout_order", new=AsyncMock(return_value=SimpleNamespace(id=order_id))),
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(_DummyCallback("s3:report_details"), state=SimpleNamespace())
            await screens.handle_callbacks(_DummyCallback("s3:report_details:back"), state=SimpleNamespace())

        self.assertEqual(show_screen.await_args_list[0].kwargs["screen_id"], "S3_INFO")
        self.assertEqual(show_screen.await_args_list[1].kwargs["screen_id"], "S3")

        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertEqual(state_snapshot.data.get("selected_tariff"), Tariff.T3.value)
        self.assertEqual(state_snapshot.data.get("order_id"), str(order_id))

    async def test_tariff_switch_resets_stale_paid_order_state(self) -> None:
        stale_order_id = self._create_order(OrderStatus.PAID)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T1.value,
            order_id=str(stale_order_id),
            order_status=OrderStatus.PAID.value,
            payment_url="https://example.com/pay",
            report_job_id="77",
            report_job_status=screens.ReportJobStatus.COMPLETED.value,
            report_text="старый отчёт",
        )

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
        self.assertIsNone(state_snapshot.data.get("order_id"))
        self.assertIsNone(state_snapshot.data.get("order_status"))
        self.assertIsNone(state_snapshot.data.get("payment_url"))
        self.assertIsNone(state_snapshot.data.get("report_job_id"))
        self.assertIsNone(state_snapshot.data.get("report_job_status"))
        self.assertIsNone(state_snapshot.data.get("report_text"))

    async def test_report_delete_confirm_all_removes_user_reports(self) -> None:
        with self.SessionLocal() as session:
            session.add_all(
                [
                    Report(user_id=1, tariff=Tariff.T1, report_text="R1"),
                    Report(user_id=1, tariff=Tariff.T2, report_text="R2"),
                ]
            )
            session.commit()

        callback = _DummyCallback("report:delete:confirm_all")
        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_send_notice", new=AsyncMock()) as send_notice,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S12")
        send_notice.assert_awaited()
        with self.SessionLocal() as session:
            reports_count = session.execute(select(func.count(Report.id))).scalar_one()
        self.assertEqual(reports_count, 0)

    async def test_profile_save_for_t2_moves_to_questionnaire(self) -> None:
        stale_order_id = self._create_order(OrderStatus.PAID)
        self._create_profile(consent_accepted=True)
        screens.screen_manager.update_state(
            1001,
            selected_tariff=Tariff.T2.value,
            order_id=str(stale_order_id),
        )
        callback = _DummyCallback("profile:save")

        with (
            patch.object(screens, "_show_screen_for_callback", new=AsyncMock()) as show_screen,
            patch.object(screens, "_send_notice", new=AsyncMock()) as send_notice,
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens, "_safe_callback_answer", new=AsyncMock()),
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        show_screen.assert_awaited_with(callback, screen_id="S5")
        send_notice.assert_not_awaited()


    async def test_prepare_checkout_order_replaces_foreign_order_from_state(self) -> None:
        with self.SessionLocal() as session:
            foreign_user = User(id=2, telegram_user_id=2002, telegram_username="foreign")
            session.add(foreign_user)
            session.flush()
            foreign_order = Order(
                user_id=foreign_user.id,
                tariff=Tariff.T1,
                amount=560,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.CREATED,
            )
            session.add(foreign_order)
            session.commit()
            foreign_order_id = foreign_order.id

        screens.screen_manager.update_state(
            1001,
            order_id=str(foreign_order_id),
            order_status=OrderStatus.PAID.value,
            payment_url="https://pay.example/foreign",
            order_amount="999",
            order_currency="USD",
        )

        callback = _DummyCallback("profile:save")

        with (
            patch.object(screens, "get_payment_provider") as get_payment_provider,
            patch.object(screens, "_send_notice", new=AsyncMock()),
        ):
            get_payment_provider.return_value = SimpleNamespace(create_payment_link=lambda *_args, **_kwargs: None)
            order = await screens._prepare_checkout_order(callback, tariff_value=Tariff.T1.value)

        self.assertIsNotNone(order)
        order_identity = inspect(order).identity
        self.assertIsNotNone(order_identity)
        new_order_id = int(order_identity[0])
        self.assertNotEqual(new_order_id, foreign_order_id)

        with self.SessionLocal() as session:
            created_order = session.get(Order, new_order_id)
            self.assertIsNotNone(created_order)
            self.assertEqual(created_order.user_id, 1)
            created_order_amount = str(int(created_order.amount))
            created_order_currency = created_order.currency

        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertEqual(state_snapshot.data.get("order_id"), str(new_order_id))
        self.assertEqual(state_snapshot.data.get("order_status"), OrderStatus.CREATED.value)
        self.assertIsNone(state_snapshot.data.get("payment_url"))
        self.assertEqual(state_snapshot.data.get("order_amount"), created_order_amount)
        self.assertEqual(state_snapshot.data.get("order_currency"), created_order_currency)

    async def test_prepare_checkout_order_replaces_consumed_paid_order_from_state(self) -> None:
        with self.SessionLocal() as session:
            consumed_order = Order(
                user_id=1,
                tariff=Tariff.T1,
                amount=560,
                currency="RUB",
                provider=PaymentProvider.PRODAMUS,
                status=OrderStatus.PAID,
                fulfillment_status=OrderFulfillmentStatus.COMPLETED,
                consumed_at=datetime.now(timezone.utc),
            )
            session.add(consumed_order)
            session.flush()
            session.add(
                Report(
                    user_id=1,
                    order_id=consumed_order.id,
                    tariff=Tariff.T1,
                    report_text="report",
                )
            )
            session.commit()
            consumed_order_id = consumed_order.id

        screens.screen_manager.update_state(
            1001,
            order_id=str(consumed_order_id),
            order_status=OrderStatus.PAID.value,
            payment_url="https://pay.example/consumed",
            order_amount="560",
            order_currency="RUB",
            selected_tariff=Tariff.T1.value,
        )

        callback = _DummyCallback("profile:save")

        with (
            patch.object(screens, "get_payment_provider") as get_payment_provider,
            patch.object(screens, "_send_notice", new=AsyncMock()),
        ):
            get_payment_provider.return_value = SimpleNamespace(create_payment_link=lambda *_args, **_kwargs: None)
            order = await screens._prepare_checkout_order(callback, tariff_value=Tariff.T1.value)

        self.assertIsNotNone(order)
        order_identity = inspect(order).identity
        self.assertIsNotNone(order_identity)
        new_order_id = int(order_identity[0])
        self.assertNotEqual(new_order_id, consumed_order_id)

        with self.SessionLocal() as session:
            created_order = session.get(Order, new_order_id)
            self.assertIsNotNone(created_order)
            self.assertEqual(created_order.status, OrderStatus.CREATED)

        state_snapshot = screens.screen_manager.update_state(1001)
        self.assertEqual(state_snapshot.data.get("order_id"), str(new_order_id))
        self.assertEqual(state_snapshot.data.get("order_status"), OrderStatus.CREATED.value)
        self.assertIsNone(state_snapshot.data.get("payment_url"))


if __name__ == "__main__":
    unittest.main()
