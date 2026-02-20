from __future__ import annotations

from datetime import datetime, timedelta
import asyncio
import logging
from typing import Any

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy import select, func

from app.bot.questionnaire.config import load_questionnaire_config, resolve_next_question_id
from app.bot.screens import build_report_wait_message
from app.bot.handlers.profile import (
    accept_marketing_consent_prompt,
    accept_profile_consent,
    accept_profile_consent_without_marketing,
    skip_marketing_consent_prompt,
    start_profile_wizard,
)
from app.bot.flows.checkout_state_machine import (
    CheckoutContext,
    resolve_checkout_entry_screen,
    resolve_checkout_transition,
)
from app.bot.handlers.screen_manager import screen_manager
from app.bot.screen_images import (
    S4_SCENARIO_AFTER_PAYMENT,
    S4_SCENARIO_PROFILE,
    S4_SCENARIO_STATE_KEY,
)
from app.core.config import settings
from app.core.timezone import APP_TIMEZONE, as_app_timezone, format_app_datetime, now_app_timezone
from app.core.pdf_service import pdf_service
from app.core.report_document import report_document_builder
from app.db.models import (
    FreeLimit,
    Order,
    OrderFulfillmentStatus,
    OrderStatus,
    PaymentProvider as PaymentProviderEnum,
    PaymentConfirmationSource,
    QuestionnaireResponse,
    QuestionnaireStatus,
    Report,
    ReportJob,
    ReportJobStatus,
    Tariff,
    User,
    UserProfile,
    FeedbackMessage,
    FeedbackStatus,
    SupportDialogMessage,
    SupportMessageDirection,
    ScreenStateRecord,
)
from app.db.session import get_session
from app.payments import get_payment_provider


router = Router()
logger = logging.getLogger(__name__)

PAID_TARIFFS = {Tariff.T1.value, Tariff.T2.value, Tariff.T3.value}
FEEDBACK_SENT_NOTICE = (
    "Сообщение отправлено администраторам. "
    "Они обязательно ответят в ближайшее время!"
)
MARKETING_CONSENT_COOLDOWN = timedelta(hours=24)


def _tariff_prices() -> dict[Tariff, int]:
    return {
        Tariff.T1: settings.tariff_prices_rub["T1"],
        Tariff.T2: settings.tariff_prices_rub["T2"],
        Tariff.T3: settings.tariff_prices_rub["T3"],
    }


def _parse_state_datetime(raw_value: Any) -> datetime | None:
    if not isinstance(raw_value, str) or not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError:
        return None
    return as_app_timezone(parsed)


def _should_show_marketing_consent_prompt(telegram_user_id: int) -> bool:
    state_snapshot = screen_manager.update_state(telegram_user_id)
    data = state_snapshot.data

    if data.get("marketing_consent_choice") == "accept":
        return False

    last_prompted_at = _parse_state_datetime(data.get("marketing_consent_last_prompted_at"))
    if not last_prompted_at:
        return True
    return now_app_timezone() - last_prompted_at >= MARKETING_CONSENT_COOLDOWN


def _mark_marketing_prompt_shown(telegram_user_id: int, *, return_screen_id: str) -> None:
    now = now_app_timezone()
    screen_manager.update_state(
        telegram_user_id,
        marketing_consent_last_prompted_at=now.isoformat(),
        marketing_consent_return_screen=return_screen_id,
    )


async def _show_marketing_consent_or_target_screen(
    callback: CallbackQuery,
    *,
    screen_id: str,
) -> bool:
    if screen_id in {"S3", "S5", "S6", "S_MARKETING_CONSENT"}:
        return await _show_screen_for_callback(callback, screen_id=screen_id)
    if not _should_show_marketing_consent_prompt(callback.from_user.id):
        return await _show_screen_for_callback(callback, screen_id=screen_id)
    _mark_marketing_prompt_shown(callback.from_user.id, return_screen_id=screen_id)
    return await _show_screen_for_callback(callback, screen_id="S_MARKETING_CONSENT")


def _reset_tariff_runtime_state(telegram_user_id: int) -> None:
    screen_manager.update_state(
        telegram_user_id,
        order_id=None,
        order_status=None,
        order_amount=None,
        order_currency=None,
        order_provider=None,
        payment_url=None,
        report_job_id=None,
        report_job_status=None,
        report_job_attempts=None,
        report_text=None,
        report_model=None,
        report_meta=None,
    )

_report_wait_tasks: dict[int, asyncio.Task[None]] = {}


_payment_wait_tasks: dict[int, asyncio.Task[None]] = {}

PAYMENT_PROVIDER_POLL_LAST_CHECKED_AT_KEY = "payment_provider_poll_last_checked_at"
PAYMENT_PROVIDER_POLL_ORDER_ID_KEY = "payment_provider_poll_order_id"


def _is_local_payment_debug_autoconfirm_enabled() -> bool:
    return settings.env.lower() in {"dev", "local"} and bool(
        getattr(settings, "payment_debug_auto_confirm_local", False)
    )


def _checkout_context_from_state(state_data: dict[str, Any]) -> CheckoutContext:
    questionnaire = state_data.get("questionnaire") or {}
    return CheckoutContext(
        tariff=state_data.get("selected_tariff"),
        profile_ready=bool(state_data.get("profile")),
        questionnaire_ready=(
            questionnaire.get("status") == QuestionnaireStatus.COMPLETED.value
        ),
        order_created=bool(_safe_int(state_data.get("order_id"))),
        payment_confirmed=(state_data.get("order_status") == OrderStatus.PAID.value),
    )


def _safe_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_quick_reply_thread_id(callback_data: str | None) -> int | None:
    prefix = "feedback:quick_reply:"
    if not callback_data or not callback_data.startswith(prefix):
        return None
    return _safe_int(callback_data.split(prefix)[-1])


def _build_feedback_records(
    *,
    user_id: int,
    feedback_text: str,
    status: FeedbackStatus,
    sent_at: datetime,
    thread_feedback_id: int | None,
) -> tuple[FeedbackMessage, SupportDialogMessage, int | None]:
    feedback = FeedbackMessage(
        user_id=user_id,
        text=feedback_text,
        status=status,
        sent_at=sent_at,
        parent_feedback_id=thread_feedback_id,
    )
    support_message = SupportDialogMessage(
        user_id=user_id,
        thread_feedback_id=thread_feedback_id or 0,
        direction=SupportMessageDirection.USER,
        text=feedback_text,
        delivered=(status == FeedbackStatus.SENT),
    )
    return feedback, support_message, thread_feedback_id


def _parse_admin_ids(value: str | None) -> list[int]:
    if not value:
        return []
    admin_ids: list[int] = []
    for raw_id in value.split(","):
        candidate = raw_id.strip()
        if not candidate:
            continue
        try:
            admin_ids.append(int(candidate))
        except ValueError:
            logger.warning("admin_id_parse_failed", extra={"value": candidate})
    return admin_ids


async def _send_feedback_to_admins(
    bot: Bot,
    *,
    feedback_text: str,
    user_id: int,
    username: str | None,
) -> bool:
    admin_ids = _parse_admin_ids(settings.admin_ids)
    if not admin_ids:
        return False
    username_label = f"@{username}" if username else "без username"
    message = (
        "Новая обратная связь\n"
        f"Пользователь: {user_id} ({username_label})\n"
        f"{feedback_text}"
    )
    delivered = False
    for admin_id in admin_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=message)
            delivered = True
        except Exception as exc:
            logger.warning(
                "feedback_admin_send_failed",
                extra={"admin_id": admin_id, "user_id": user_id, "error": str(exc)},
            )
    return delivered


async def _submit_feedback(
    bot: Bot,
    *,
    user_id: int,
    username: str | None,
    feedback_text: str,
) -> FeedbackStatus:
    delivered = await _send_feedback_to_admins(
        bot,
        feedback_text=feedback_text,
        user_id=user_id,
        username=username,
    )
    status = FeedbackStatus.SENT if delivered else FeedbackStatus.FAILED
    sent_at = now_app_timezone()

    try:
        with get_session() as session:
            user = _get_or_create_user(session, user_id)
            state = screen_manager.update_state(user_id)
            thread_feedback_id = _safe_int(state.data.get("support_thread_feedback_id"))
            if not thread_feedback_id:
                thread_feedback_id = None
            feedback, support_message, _ = _build_feedback_records(
                user_id=user.id,
                feedback_text=feedback_text,
                status=status,
                sent_at=sent_at,
                thread_feedback_id=thread_feedback_id,
            )
            session.add(feedback)
            session.flush()
            support_message.thread_feedback_id = thread_feedback_id or feedback.id
            session.add(support_message)
            screen_manager.update_state(
                user_id, support_thread_feedback_id=thread_feedback_id or feedback.id
            )
    except Exception as exc:
        logger.warning(
            "feedback_store_failed",
            extra={"user_id": user_id, "error": str(exc)},
        )

    return status


async def _run_report_delay(bot: Bot, chat_id: int, user_id: int) -> None:
    cycle_seconds = max(settings.report_delay_seconds, 1)
    frames = ["⏳", "⌛", "🔄", "✨"]
    tick = 0
    while True:
        state = screen_manager.update_state(user_id)
        if not state.message_ids:
            return
        message_id = state.message_ids[-1]
        with get_session() as session:
            job = _refresh_report_job_state(session, user_id)
            job_status = job.status if job else None
        if job_status in {ReportJobStatus.COMPLETED, ReportJobStatus.FAILED}:
            return
        frame = frames[tick % len(frames)]
        raw_progress = ((tick % cycle_seconds) + 1) / cycle_seconds
        progress = min(max(raw_progress, 0.05), 0.95)
        text = build_report_wait_message(
            frame=frame,
            progress=progress,
        )
        content = screen_manager.render_screen("S6", user_id, state.data)
        try:
            await _edit_report_wait_message(
                bot=bot,
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=content.keyboard,
                parse_mode=content.parse_mode,
            )
        except Exception as exc:
            logger.info(
                "report_delay_edit_failed",
                extra={
                    "user_id": user_id,
                    "message_id": message_id,
                    "error": str(exc),
                },
            )
            return
        tick += 1
        await asyncio.sleep(1)


async def _edit_report_wait_message(
    *,
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: Any,
    parse_mode: str | None,
) -> None:
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return
    except TelegramBadRequest as exc:
        error_message = str(exc)
        if "there is no text in the message to edit" not in error_message.lower():
            raise
    await bot.edit_message_caption(
        chat_id=chat_id,
        message_id=message_id,
        caption=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )


async def _run_payment_waiter(bot: Bot, chat_id: int, user_id: int) -> None:
    poll_interval = max(settings.report_delay_seconds, 1)
    while True:
        state = screen_manager.update_state(user_id)
        order_id = _safe_int(state.data.get("order_id"))
        if not order_id:
            return
        with get_session() as session:
            order = session.get(Order, order_id)
            if not order:
                return

            state_snapshot = screen_manager.update_state(user_id)
            state_data = state_snapshot.data
            current_time = now_app_timezone()

            if order.status != OrderStatus.PAID:
                min_poll_interval_seconds = max(
                    int(getattr(settings, "payment_provider_poll_min_interval_seconds", 10) or 10),
                    1,
                )
                last_poll_order_id = _safe_int(state_data.get(PAYMENT_PROVIDER_POLL_ORDER_ID_KEY))
                last_poll_at = _parse_state_datetime(
                    state_data.get(PAYMENT_PROVIDER_POLL_LAST_CHECKED_AT_KEY)
                )
                should_poll_provider = (
                    last_poll_order_id != order.id
                    or not last_poll_at
                    or (current_time - last_poll_at).total_seconds() >= min_poll_interval_seconds
                )
                if should_poll_provider:
                    screen_manager.update_state(
                        user_id,
                        **{
                            PAYMENT_PROVIDER_POLL_ORDER_ID_KEY: str(order.id),
                            PAYMENT_PROVIDER_POLL_LAST_CHECKED_AT_KEY: current_time.isoformat(),
                        },
                    )
                    try:
                        provider = get_payment_provider(order.provider.value)
                        poll_result = provider.check_payment_status(order)
                    except Exception as exc:
                        logger.warning(
                            "payment_provider_poll_failed",
                            extra={
                                "order_id": order.id,
                                "provider": order.provider.value,
                                "error": str(exc),
                            },
                        )
                        poll_result = None

                    if poll_result and getattr(poll_result, "is_paid", False):
                        provider_payment_id = getattr(poll_result, "provider_payment_id", None)
                        if order.status != OrderStatus.PAID:
                            order.status = OrderStatus.PAID
                            order.paid_at = current_time
                        if not order.payment_confirmed_at:
                            order.payment_confirmed_at = current_time
                        order.payment_confirmed = True
                        order.payment_confirmation_source = PaymentConfirmationSource.PROVIDER_POLL
                        if provider_payment_id and not order.provider_payment_id:
                            order.provider_payment_id = str(provider_payment_id)
                        session.add(order)
                        session.flush()

            screen_manager.update_state(user_id, **_refresh_order_state(order))
            if order.status == OrderStatus.PAID:
                _refresh_profile_state(session, user_id)
                _refresh_questionnaire_state(session, user_id)
                state_snapshot = screen_manager.update_state(user_id)
                selected_tariff = state_snapshot.data.get("selected_tariff")
                questionnaire = state_snapshot.data.get("questionnaire") or {}

                profile = state_snapshot.data.get("profile")
                target_screen_id = "S4"
                if profile and selected_tariff in {Tariff.T2.value, Tariff.T3.value} and (
                    questionnaire.get("status") != QuestionnaireStatus.COMPLETED.value
                ):
                    target_screen_id = "S5"
                elif profile and selected_tariff in PAID_TARIFFS:
                    user = _get_or_create_user(session, user_id)
                    _create_report_job(
                        session,
                        user=user,
                        tariff_value=selected_tariff,
                        order_id=order.id,
                        chat_id=chat_id,
                    )
                    target_screen_id = "S6"
                screen_manager.update_state(
                    user_id,
                    profile_flow="report",
                    payment_processing_notice=False,
                    **{S4_SCENARIO_STATE_KEY: S4_SCENARIO_AFTER_PAYMENT},
                )
                await screen_manager.show_screen(
                    bot=bot,
                    chat_id=chat_id,
                    user_id=user_id,
                    screen_id=target_screen_id,
                    trigger_type="auto",
                    trigger_value="payment_confirmed",
                )
                if target_screen_id == "S6" and settings.report_delay_seconds > 0:
                    running_task = _report_wait_tasks.get(user_id)
                    if not running_task or running_task.done():
                        _report_wait_tasks[user_id] = asyncio.create_task(
                            _run_report_delay(bot=bot, chat_id=chat_id, user_id=user_id)
                        )
                return
        await asyncio.sleep(poll_interval)


async def _maybe_run_payment_waiter(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    await ensure_payment_waiter(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
    )


async def ensure_payment_waiter(*, bot: Bot, chat_id: int, user_id: int) -> None:
    running_task = _payment_wait_tasks.get(user_id)
    if running_task and not running_task.done():
        return

    async def _runner() -> None:
        try:
            await _run_payment_waiter(
                bot=bot,
                chat_id=chat_id,
                user_id=user_id,
            )
        finally:
            _payment_wait_tasks.pop(user_id, None)

    _payment_wait_tasks[user_id] = asyncio.create_task(_runner())


def _iter_payment_waiter_candidates() -> list[tuple[int, int]]:
    candidates: list[tuple[int, int]] = []
    with get_session() as session:
        rows = session.execute(
            select(ScreenStateRecord).where(ScreenStateRecord.screen_id == "S3")
        ).scalars().all()
        for row in rows:
            state_data = row.data or {}
            order_id = _safe_int(state_data.get("order_id"))
            if not order_id:
                continue
            candidates.append((row.telegram_user_id, order_id))
    return candidates


async def restore_payment_waiters(bot: Bot) -> int:
    restored = 0
    for user_id, order_id in _iter_payment_waiter_candidates():
        with get_session() as session:
            order = session.get(Order, order_id)
            if not order:
                continue
            user = _get_or_create_user(session, user_id)
            if order.user_id != user.id:
                continue
            if order.status == OrderStatus.PAID:
                continue
        await ensure_payment_waiter(
            bot=bot,
            chat_id=user_id,
            user_id=user_id,
        )
        restored += 1
    if restored:
        logger.info("payment_waiters_restored", extra={"count": restored})
    return restored


async def _maybe_run_report_delay(callback: CallbackQuery) -> None:
    if settings.report_delay_seconds <= 0:
        return
    if not callback.message:
        return
    user_id = callback.from_user.id
    running_task = _report_wait_tasks.get(user_id)
    if running_task and not running_task.done():
        return
    state_snapshot = screen_manager.update_state(user_id)
    if state_snapshot.data.get("report_job_status") == ReportJobStatus.FAILED.value:
        return

    async def _runner() -> None:
        try:
            await _run_report_delay(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                user_id=user_id,
            )
        finally:
            _report_wait_tasks.pop(user_id, None)

    _report_wait_tasks[user_id] = asyncio.create_task(_runner())


async def _safe_callback_answer(callback: CallbackQuery) -> None:
    if getattr(callback, "answered", False) or getattr(callback, "_answered", False):
        return
    try:
        await callback.answer()
        setattr(callback, "_answered", True)
    except TelegramBadRequest as exc:
        message = str(exc)
        if "query is too old" in message or "query ID is invalid" in message:
            logger.warning(
                "callback_answer_expired",
                extra={"user_id": callback.from_user.id, "error": message},
            )
            setattr(callback, "_answered", True)
            return
        raise
    except (TelegramNetworkError, TimeoutError) as exc:
        logger.warning(
            "callback_answer_network_issue",
            extra={"user_id": callback.from_user.id, "error": str(exc)},
        )


async def _safe_callback_processing(callback: CallbackQuery) -> None:
    if getattr(callback, "answered", False) or getattr(callback, "_answered", False):
        return
    try:
        await callback.answer("Обрабатываю…")
        setattr(callback, "_answered", True)
    except TelegramBadRequest as exc:
        message = str(exc)
        if "query is too old" in message or "query ID is invalid" in message:
            logger.warning(
                "callback_answer_expired",
                extra={"user_id": callback.from_user.id, "error": message},
            )
            setattr(callback, "_answered", True)
            return
        raise
    except (TelegramNetworkError, TimeoutError) as exc:
        logger.warning(
            "callback_processing_network_issue",
            extra={"user_id": callback.from_user.id, "error": str(exc)},
        )


async def _ensure_report_delivery(callback: CallbackQuery, screen_id: str) -> bool:
    delivered = await _show_screen_for_callback(
        callback,
        screen_id=screen_id,
    )
    if delivered:
        return True
    if callback.message:
        await screen_manager.send_ephemeral_message(
            callback.message,
            "Извините, произошла техническая заминка при отправке отчёта. Сейчас повторю запрос.",
            user_id=callback.from_user.id,
        )
    await asyncio.sleep(1)
    delivered = await _show_screen_for_callback(
        callback,
        screen_id=screen_id,
    )
    if not delivered:
        logger.warning(
            "report_delivery_failed",
            extra={"user_id": callback.from_user.id, "screen_id": screen_id},
        )
    return delivered


async def _send_notice(callback: CallbackQuery, text: str, **kwargs: Any) -> None:
    await screen_manager.send_ephemeral_message(
        callback.message,
        text,
        user_id=callback.from_user.id,
        **kwargs,
    )


async def _show_reports_list_with_refresh(callback: CallbackQuery) -> None:
    with get_session() as session:
        _refresh_reports_list_state(session, callback.from_user.id)
    screen_manager.update_state(
        callback.from_user.id,
        report_text=None,
        report_meta=None,
    )
    await _show_screen_for_callback(
        callback,
        screen_id="S12",
    )


async def _show_screen_for_callback(
    callback: CallbackQuery,
    *,
    screen_id: str,
    metadata_json: dict[str, Any] | None = None,
) -> bool:
    if screen_id == "S4":
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        scenario = state_snapshot.data.get(S4_SCENARIO_STATE_KEY)
        if scenario not in {S4_SCENARIO_PROFILE, S4_SCENARIO_AFTER_PAYMENT}:
            screen_manager.update_state(
                callback.from_user.id,
                **{S4_SCENARIO_STATE_KEY: S4_SCENARIO_PROFILE},
            )
    if screen_id == "S8":
        await screen_manager.enter_text_input_mode(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
        )
    return await screen_manager.show_screen(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        screen_id=screen_id,
        trigger_type="callback",
        trigger_value=callback.data,
        metadata_json=metadata_json,
    )


async def show_post_report_screen(bot: Bot, chat_id: int, user_id: int) -> bool:
    target_screen_id = "S7"
    if _should_show_marketing_consent_prompt(user_id):
        _mark_marketing_prompt_shown(user_id, return_screen_id=target_screen_id)
        target_screen_id = "S_MARKETING_CONSENT"
    return await screen_manager.show_screen(
        bot=bot,
        chat_id=chat_id,
        user_id=user_id,
        screen_id=target_screen_id,
        trigger_type="job",
        trigger_value="report_job:completed",
        metadata_json={"reason": "report_completed_post_prompt"},
    )


def _missing_payment_link_config(provider: PaymentProviderEnum) -> list[str]:
    missing: list[str] = []
    if provider == PaymentProviderEnum.PRODAMUS:
        if not settings.prodamus_form_url:
            missing.append("PRODAMUS_FORM_URL")
    elif provider == PaymentProviderEnum.CLOUDPAYMENTS:
        if not settings.cloudpayments_public_id:
            missing.append("CLOUDPAYMENTS_PUBLIC_ID")
    return missing


def _missing_payment_status_config(provider: PaymentProviderEnum) -> list[str]:
    missing: list[str] = []
    if provider == PaymentProviderEnum.PRODAMUS:
        # Для Prodamus статус подтверждается webhook-уведомлением от формы оплаты.
        # Дополнительный status endpoint не требуется.
        if not settings.prodamus_unified_key:
            missing.append("PRODAMUS_KEY (или PRODAMUS_API_KEY / PRODAMUS_SECRET / PRODAMUS_WEBHOOK_SECRET)")
    elif provider == PaymentProviderEnum.CLOUDPAYMENTS:
        if not settings.cloudpayments_public_id:
            missing.append("CLOUDPAYMENTS_PUBLIC_ID")
        if not settings.cloudpayments_api_secret:
            missing.append("CLOUDPAYMENTS_API_SECRET")
    return missing


def _get_payment_provider() -> PaymentProviderEnum:
    provider = settings.payment_provider.lower()
    if provider == PaymentProviderEnum.PRODAMUS.value:
        if not settings.prodamus_form_url and settings.cloudpayments_public_id:
            return PaymentProviderEnum.CLOUDPAYMENTS
        return PaymentProviderEnum.PRODAMUS
    if provider == PaymentProviderEnum.CLOUDPAYMENTS.value:
        if not settings.cloudpayments_public_id and settings.prodamus_form_url:
            return PaymentProviderEnum.PRODAMUS
        return PaymentProviderEnum.CLOUDPAYMENTS
    return PaymentProviderEnum.PRODAMUS


def _get_or_create_user(
    session, telegram_user_id: int, telegram_username: str | None = None
) -> User:
    user = session.execute(
        select(User).where(User.telegram_user_id == telegram_user_id)
    ).scalar_one_or_none()
    if user:
        if telegram_username is not None:
            user.telegram_username = telegram_username
        if not user.free_limit:
            free_limit = session.execute(
                select(FreeLimit).where(FreeLimit.user_id == user.id)
            ).scalar_one_or_none()
            if free_limit:
                user.free_limit = free_limit
            else:
                free_limit = FreeLimit(user_id=user.id)
                session.add(free_limit)
                user.free_limit = free_limit
        return user

    user = User(telegram_user_id=telegram_user_id, telegram_username=telegram_username)
    session.add(user)
    session.flush()
    free_limit = FreeLimit(user_id=user.id)
    session.add(free_limit)
    user.free_limit = free_limit
    return user


def _profile_payload(
    profile: UserProfile | None,
) -> dict[str, Any]:
    if not profile:
        return {
            "profile": None,
            "personal_data_consent_accepted": False,
            "personal_data_consent_accepted_at": None,
            "personal_data_consent_source": None,
        }
    return {
        "profile": {
            "name": profile.name,
            "gender": profile.gender,
            "birth_date": profile.birth_date,
            "birth_time": profile.birth_time,
            "birth_place": {
                "city": profile.birth_place_city,
                "region": profile.birth_place_region,
                "country": profile.birth_place_country,
            },
            "personal_data_consent_accepted": bool(profile.personal_data_consent_accepted_at),
            "personal_data_consent_accepted_at": (
                profile.personal_data_consent_accepted_at.isoformat()
                if profile.personal_data_consent_accepted_at
                else None
            ),
            "personal_data_consent_source": profile.personal_data_consent_source,
        },
        "personal_data_consent_accepted": bool(profile.personal_data_consent_accepted_at),
        "personal_data_consent_accepted_at": (
            profile.personal_data_consent_accepted_at.isoformat()
            if profile.personal_data_consent_accepted_at
            else None
        ),
        "personal_data_consent_source": profile.personal_data_consent_source,
    }


def _refresh_profile_state(session, telegram_user_id: int) -> None:
    user = _get_or_create_user(session, telegram_user_id)
    screen_manager.update_state(telegram_user_id, **_profile_payload(user.profile))


def _t0_cooldown_status(session, telegram_user_id: int) -> tuple[bool, str | None]:
    user = _get_or_create_user(session, telegram_user_id)
    free_limit = user.free_limit
    last_t0_at = free_limit.last_t0_at if free_limit else None
    if last_t0_at and last_t0_at.tzinfo is None:
        last_t0_at = last_t0_at.replace(tzinfo=APP_TIMEZONE)
    cooldown = timedelta(hours=settings.free_t0_cooldown_hours)
    now = now_app_timezone()
    if last_t0_at and now < last_t0_at + cooldown:
        next_available = last_t0_at + cooldown
        return False, format_app_datetime(next_available)
    return True, None


def _refresh_questionnaire_state(session, telegram_user_id: int) -> None:
    config = load_questionnaire_config()
    response = session.execute(
        select(QuestionnaireResponse).where(
            QuestionnaireResponse.user_id
            == _get_or_create_user(session, telegram_user_id).id,
            QuestionnaireResponse.questionnaire_version == config.version,
        )
    ).scalar_one_or_none()
    answers = response.answers if response and response.answers else {}
    actual_answers: dict[str, Any] = {}
    current_question_id = config.start_question_id
    visited: set[str] = set()
    while current_question_id and current_question_id not in visited:
        question = config.get_question(current_question_id)
        if not question:
            current_question_id = None
            break
        visited.add(current_question_id)
        if current_question_id not in answers:
            break
        answer = answers[current_question_id]
        actual_answers[current_question_id] = answer
        next_question_id = resolve_next_question_id(question, answer)
        if next_question_id is None:
            current_question_id = None
            break
        if next_question_id not in config.questions:
            current_question_id = None
            break
        current_question_id = next_question_id

    resolved_status = response.status.value if response else "empty"
    completed_at = response.completed_at if response else None
    if response:
        answers = actual_answers
        if current_question_id is None and actual_answers:
            resolved_status = QuestionnaireStatus.COMPLETED.value
            if response.status != QuestionnaireStatus.COMPLETED:
                response.status = QuestionnaireStatus.COMPLETED
                if response.completed_at is None:
                    response.completed_at = now_app_timezone()
            if response.current_question_id is not None:
                response.current_question_id = None
            if response.answers != actual_answers:
                response.answers = actual_answers
            completed_at = response.completed_at
        elif response.answers != actual_answers:
            response.answers = actual_answers
            answers = actual_answers
    else:
        answers = actual_answers

    screen_manager.update_state(
        telegram_user_id,
        questionnaire={
            "version": config.version,
            "status": resolved_status,
            "answers": answers,
            "current_question_id": current_question_id if response else None,
            "answered_count": len(answers),
            "total_questions": len(config.questions),
            "completed_at": (
                completed_at.isoformat()
                if completed_at
                else None
            ),
        },
    )


def _refresh_report_state(
    session,
    telegram_user_id: int,
    *,
    tariff_value: str | None,
) -> None:
    user = _get_or_create_user(session, telegram_user_id)
    query = select(Report).where(Report.user_id == user.id)
    if tariff_value:
        try:
            query = query.where(Report.tariff == Tariff(tariff_value))
        except ValueError:
            pass
    report = (
        session.execute(query.order_by(Report.created_at.desc()).limit(1))
        .scalars()
        .first()
    )
    if report:
        screen_manager.update_state(
            telegram_user_id,
            report_text=report.report_text,
            report_model=report.model_used.value if report.model_used else None,
        )


def _refresh_report_job_state(
    session,
    telegram_user_id: int,
    *,
    job_id: int | None = None,
    expected_tariff_value: str | None = None,
    expected_order_id: int | None = None,
) -> ReportJob | None:
    user = _get_or_create_user(session, telegram_user_id)
    resolved_job_id = job_id
    if resolved_job_id is None:
        state_snapshot = screen_manager.update_state(telegram_user_id)
        resolved_job_id = _safe_int(state_snapshot.data.get("report_job_id"))
    if not resolved_job_id:
        screen_manager.update_state(
            telegram_user_id,
            report_job_id=None,
            report_job_status=None,
            report_job_attempts=None,
        )
        return None
    job = session.get(ReportJob, resolved_job_id)
    if not job or job.user_id != user.id:
        screen_manager.update_state(
            telegram_user_id,
            report_job_id=None,
            report_job_status=None,
            report_job_attempts=None,
        )
        return None
    if expected_tariff_value:
        try:
            expected_tariff = Tariff(expected_tariff_value)
        except ValueError:
            expected_tariff = None
        if expected_tariff and job.tariff != expected_tariff:
            screen_manager.update_state(
                telegram_user_id,
                report_job_id=None,
                report_job_status=None,
                report_job_attempts=None,
            )
            return None
    if expected_order_id is not None and job.order_id != expected_order_id:
        screen_manager.update_state(
            telegram_user_id,
            report_job_id=None,
            report_job_status=None,
            report_job_attempts=None,
        )
        return None
    screen_manager.update_state(
        telegram_user_id,
        report_job_id=str(job.id),
        report_job_status=job.status.value,
        report_job_attempts=job.attempts,
    )
    return job


def _create_report_job(
    session,
    *,
    user: User,
    tariff_value: str | None,
    order_id: int | None,
    chat_id: int | None,
) -> ReportJob | None:
    if not tariff_value:
        return None
    try:
        tariff = Tariff(tariff_value)
    except ValueError:
        return None
    if tariff in PAID_TARIFFS:
        if order_id is None:
            return None
        order = session.get(Order, order_id)
        if not order:
            return None
        if order.user_id != user.id:
            return None
        if order.tariff != tariff:
            return None
        if order.status != OrderStatus.PAID:
            return None
        expected_amount = _tariff_prices().get(tariff)
        if expected_amount is not None and float(order.amount or 0) != float(expected_amount):
            return None
    else:
        order_id = None
    query = select(ReportJob).where(
        ReportJob.user_id == user.id,
        ReportJob.tariff == tariff,
        ReportJob.status.in_([ReportJobStatus.PENDING, ReportJobStatus.IN_PROGRESS]),
    )
    if order_id is None:
        query = query.where(ReportJob.order_id.is_(None))
    else:
        query = query.where(ReportJob.order_id == order_id)
    existing_job = (
        session.execute(query.order_by(ReportJob.created_at.desc()).limit(1))
        .scalars()
        .first()
    )
    if existing_job:
        existing_job.chat_id = chat_id
        session.add(existing_job)
        screen_manager.update_state(
            user.telegram_user_id,
            report_job_id=str(existing_job.id),
            report_job_status=existing_job.status.value,
            report_job_attempts=existing_job.attempts,
        )
        return existing_job
    job = ReportJob(
        user_id=user.id,
        order_id=order_id,
        tariff=tariff,
        status=ReportJobStatus.PENDING,
        attempts=0,
        chat_id=chat_id,
    )
    session.add(job)
    session.flush()
    screen_manager.update_state(
        user.telegram_user_id,
        report_job_id=str(job.id),
        report_job_status=job.status.value,
        report_job_attempts=job.attempts,
    )
    return job


def _requeue_report_job(
    session,
    *,
    telegram_user_id: int,
    job: ReportJob,
) -> ReportJob:
    job.status = ReportJobStatus.PENDING
    job.last_error = None
    job.lock_token = None
    job.locked_at = None
    session.add(job)
    screen_manager.update_state(
        telegram_user_id,
        report_job_id=str(job.id),
        report_job_status=job.status.value,
        report_job_attempts=job.attempts,
    )
    return job


def _get_latest_report(
    session,
    telegram_user_id: int,
    *,
    tariff_value: str | None,
) -> Report | None:
    user = _get_or_create_user(session, telegram_user_id)
    query = select(Report).where(Report.user_id == user.id)
    if tariff_value:
        try:
            query = query.where(Report.tariff == Tariff(tariff_value))
        except ValueError:
            logger.warning(
                "report_tariff_invalid",
                extra={"user_id": telegram_user_id, "tariff": tariff_value},
            )
    return (
        session.execute(query.order_by(Report.created_at.desc()).limit(1))
        .scalars()
        .first()
    )


def _get_report_for_order(session, order_id: int) -> Report | None:
    return (
        session.execute(select(Report).where(Report.order_id == order_id).limit(1))
        .scalars()
        .first()
    )


def _get_user(session, telegram_user_id: int) -> User | None:
    return session.execute(
        select(User).where(User.telegram_user_id == telegram_user_id)
    ).scalar_one_or_none()


def _format_report_created_at(created_at: datetime | None) -> str:
    if not isinstance(created_at, datetime):
        return "неизвестно"
    value = created_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=APP_TIMEZONE)
    return format_app_datetime(value)


def _refresh_reports_list_state(
    session, telegram_user_id: int, *, limit: int = 10
) -> None:
    user = _get_user(session, telegram_user_id)
    if not user:
        screen_manager.update_state(
            telegram_user_id,
            reports=[],
            reports_total=0,
        )
        return
    total = (
        session.execute(
            select(func.count(Report.id)).where(Report.user_id == user.id)
        ).scalar()
        or 0
    )
    reports = (
        session.execute(
            select(Report)
            .where(Report.user_id == user.id)
            .order_by(Report.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    report_entries = []
    for report in reports:
        tariff_value = (
            report.tariff.value
            if isinstance(report.tariff, Tariff)
            else str(report.tariff)
        )
        report_entries.append(
            {
                "id": report.id,
                "tariff": tariff_value,
                "created_at": _format_report_created_at(report.created_at),
            }
        )
    screen_manager.update_state(
        telegram_user_id,
        reports=report_entries,
        reports_total=total,
    )


def _store_existing_tariff_report_state(
    telegram_user_id: int,
    report: Report | None,
) -> None:
    screen_manager.update_state(
        telegram_user_id,
        existing_tariff_report_found=bool(report),
        existing_tariff_report_meta=_report_meta_payload(report) if report else None,
    )


def _get_report_for_user(
    session, telegram_user_id: int, report_id: int
) -> Report | None:
    user = _get_user(session, telegram_user_id)
    if not user:
        return None
    return session.execute(
        select(Report).where(Report.user_id == user.id, Report.id == report_id)
    ).scalar_one_or_none()


def _get_reports_for_user(session, telegram_user_id: int) -> list[Report]:
    user = _get_user(session, telegram_user_id)
    if not user:
        return []
    return (
        session.execute(
            select(Report)
            .where(Report.user_id == user.id)
            .order_by(Report.created_at.desc(), Report.id.desc())
        )
        .scalars()
        .all()
    )


def _report_meta_payload(report: Report) -> dict[str, str]:
    tariff_value = (
        report.tariff.value if isinstance(report.tariff, Tariff) else str(report.tariff)
    )
    return {
        "id": str(report.id),
        "tariff": tariff_value,
        "created_at": _format_report_created_at(report.created_at),
    }


def _delete_report_with_assets(session, report: Report) -> bool:
    try:
        pdf_service.delete_pdf(report.pdf_storage_key)
    except Exception as exc:
        logger.warning(
            "report_pdf_delete_failed",
            extra={
                "report_id": report.id,
                "pdf_storage_key": report.pdf_storage_key,
                "error": str(exc),
            },
        )
    try:
        linked_orders: list[Order] = []
        try:
            linked_orders_raw = (
                session.execute(select(Order).where(Order.fulfilled_report_id == report.id))
                .scalars()
                .all()
            )
            linked_orders = linked_orders_raw if isinstance(linked_orders_raw, list) else []
        except Exception as exc:
            logger.warning(
                "report_linked_orders_fetch_failed",
                extra={"report_id": report.id, "error": str(exc)},
            )
        for linked_order in linked_orders:
            linked_order.fulfilled_report_id = None
            if linked_order.fulfillment_status == OrderFulfillmentStatus.COMPLETED:
                linked_order.fulfillment_status = OrderFulfillmentStatus.PENDING
                linked_order.fulfilled_at = None
            session.add(linked_order)
        session.delete(report)
        session.flush()
        return True
    except Exception as exc:
        logger.warning(
            "report_db_delete_failed",
            extra={"report_id": report.id, "error": str(exc)},
        )
        return False


def _get_report_pdf_bytes(session, report: Report) -> bytes | None:
    pdf_bytes = None
    if report.pdf_storage_key:
        pdf_bytes = pdf_service.load_pdf(report.pdf_storage_key)
    if pdf_bytes is None:
        try:
            report_document = report_document_builder.build(
                report.report_text or "",
                tariff=report.tariff,
                meta=_get_report_pdf_meta(report),
            )
            pdf_bytes = pdf_service.generate_pdf(
                report.report_text or "",
                tariff=report.tariff,
                meta=_get_report_pdf_meta(report),
                report_document=report_document,
            )
        except Exception as exc:
            logger.warning(
                "pdf_generate_failed",
                extra={"report_id": report.id, "error": str(exc)},
            )
            return None
        storage_key = pdf_service.store_pdf(report.id, pdf_bytes)
        if storage_key:
            report.pdf_storage_key = storage_key
            session.add(report)
    return pdf_bytes


def _get_report_pdf_meta(report: Report | None) -> dict | None:
    if not report:
        return None
    report_id = str(report.id) if report.id is not None else "report"
    if isinstance(report.tariff, Tariff):
        tariff_value = report.tariff.value
    else:
        tariff_value = str(report.tariff or "tariff")
    created_at_value = (
        report.created_at if isinstance(report.created_at, datetime) else None
    )
    return {
        "id": report_id,
        "tariff": tariff_value,
        "created_at": created_at_value,
    }


def _build_report_pdf_filename(
    report_meta: dict | None, username: str | None, user_id: int | None
) -> str:
    if username:
        raw_username = str(username)
        display_username = (
            raw_username if raw_username.startswith("@") else f"@{raw_username}"
        )
    elif user_id is not None:
        display_username = f"@user_{user_id}"
    else:
        display_username = "@unknown"
    tariff_value = "tariff"
    created_at_value = "unknown-time"
    report_id = "report"
    if report_meta:
        report_id = str(report_meta.get("id") or report_id)
        tariff_value = str(report_meta.get("tariff") or tariff_value)
        created_at = report_meta.get("created_at")
        if isinstance(created_at, datetime):
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=APP_TIMEZONE)
            created_at_value = as_app_timezone(created_at).strftime("%Y%m%d-%H%M%S")
    return f"{display_username}_{tariff_value}_{created_at_value}_{report_id}.pdf"


async def _send_report_pdf(
    bot,
    chat_id: int,
    report_meta: dict | None,
    *,
    pdf_bytes: bytes | None,
    username: str | None,
    user_id: int,
) -> bool:
    if not pdf_bytes:
        return False
    stored_username = username
    if stored_username is None:
        with get_session() as session:
            user = session.execute(
                select(User).where(User.telegram_user_id == user_id)
            ).scalar_one_or_none()
            if user and user.telegram_username is not None:
                stored_username = user.telegram_username
    filename = _build_report_pdf_filename(report_meta, stored_username, user_id)
    report_id = report_meta.get("id") if report_meta else None
    try:
        sent = await bot.send_document(
            chat_id, BufferedInputFile(pdf_bytes, filename=filename)
        )
    except Exception as exc:
        logger.warning(
            "pdf_send_failed",
            extra={"report_id": report_id, "error": str(exc)},
        )
        return False
    screen_manager.add_pdf_message_id(user_id, sent.message_id)
    return True


def _ensure_profile_state(telegram_user_id: int) -> None:
    with get_session() as session:
        _refresh_profile_state(session, telegram_user_id)


def _create_order(session, user: User, tariff: Tariff) -> Order:
    order = Order(
        user_id=user.id,
        tariff=tariff,
        amount=_tariff_prices()[tariff],
        currency="RUB",
        provider=_get_payment_provider(),
        status=OrderStatus.CREATED,
    )
    session.add(order)
    session.flush()
    return order


def _get_reusable_paid_order(
    session,
    telegram_user_id: int,
    tariff_value: str | None,
) -> Order | None:
    if tariff_value not in PAID_TARIFFS:
        return None
    user = _get_user(session, telegram_user_id)
    if not user:
        return None
    try:
        tariff = Tariff(tariff_value)
    except ValueError:
        return None
    expected_amount = _tariff_prices().get(tariff)
    if expected_amount is None:
        return None
    return (
        session.execute(
            select(Order)
            .where(
                Order.user_id == user.id,
                Order.tariff == tariff,
                Order.amount == expected_amount,
                Order.status == OrderStatus.PAID,
                Order.fulfillment_status == OrderFulfillmentStatus.PENDING,
                Order.fulfilled_report_id.is_(None),
                ~select(Report.id)
                .where(Report.order_id == Order.id)
                .exists(),
            )
            .order_by(Order.paid_at.desc(), Order.created_at.desc(), Order.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def _refresh_order_state(order: Order) -> dict[str, str]:
    return {
        "order_id": str(order.id),
        "order_status": order.status.value,
        "order_amount": str(order.amount),
        "order_currency": order.currency,
    }


def _safe_create_payment_link(provider, order: Order, user: User | None):
    try:
        return provider.create_payment_link(order, user=user)
    except Exception:
        logger.exception(
            "payment_link_create_failed",
            extra={
                "order_id": order.id,
                "provider": order.provider.value,
                "user_id": user.id if user else None,
            },
        )
        return None


async def _prepare_checkout_order(
    callback: CallbackQuery,
    *,
    tariff_value: str | None,
    force_new_order: bool = False,
) -> Order | None:
    if tariff_value not in PAID_TARIFFS:
        return None
    try:
        tariff = Tariff(tariff_value)
    except ValueError:
        return None

    state_snapshot = screen_manager.update_state(callback.from_user.id)
    with get_session() as session:
        user = _get_or_create_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
        )
        order: Order | None = None
        if not force_new_order:
            order_id = _safe_int(state_snapshot.data.get("order_id"))
            state_order_not_usable = False
            if order_id:
                order = session.get(Order, order_id)
                if order and order.user_id != user.id:
                    logger.warning(
                        "checkout_order_owner_mismatch",
                        extra={
                            "telegram_user_id": callback.from_user.id,
                            "order_id": order_id,
                            "order_user_id": order.user_id,
                        },
                    )
                    order = None
                    state_order_not_usable = True
                if order and order.tariff != tariff:
                    order = None
                    state_order_not_usable = True
                expected_amount = _tariff_prices().get(tariff)
                if (
                    order
                    and expected_amount is not None
                    and float(order.amount or 0) != float(expected_amount)
                ):
                    order = None
                    state_order_not_usable = True
                if order and order.status in {
                    OrderStatus.FAILED,
                    OrderStatus.CANCELED,
                }:
                    order = None
                    state_order_not_usable = True
                if order and order.status == OrderStatus.PAID:
                    paid_order_consumed = bool(order.fulfilled_report_id) or (
                        order.fulfillment_status == OrderFulfillmentStatus.COMPLETED
                    )
                    if not paid_order_consumed:
                        paid_order_consumed = (
                            session.execute(
                                select(Report.id)
                                .where(Report.order_id == order.id)
                                .limit(1)
                            ).scalar_one_or_none()
                            is not None
                        )
                    if paid_order_consumed:
                        order = None
                        state_order_not_usable = True
                if not order:
                    state_order_not_usable = True

                if state_order_not_usable:
                    screen_manager.update_state(
                        callback.from_user.id,
                        order_id=None,
                        order_status=None,
                        order_amount=None,
                        order_currency=None,
                        order_provider=None,
                        payment_url=None,
                    )
                    force_new_order = True

        if not order and not force_new_order:
            order = _get_reusable_paid_order(session, callback.from_user.id, tariff_value)

        if not order:
            order = _create_order(session, user, tariff)

        payment_link = None
        if settings.payment_enabled and order.status != OrderStatus.PAID:
            provider = get_payment_provider(order.provider.value)
            payment_link = _safe_create_payment_link(
                provider,
                order,
                user,
            )
            if not payment_link and order.provider == PaymentProviderEnum.PRODAMUS:
                fallback_provider = get_payment_provider(
                    PaymentProviderEnum.CLOUDPAYMENTS.value
                )
                payment_link = _safe_create_payment_link(
                    fallback_provider,
                    order,
                    user,
                )
                if payment_link:
                    order.provider = PaymentProviderEnum.CLOUDPAYMENTS
                    session.add(order)
            if not payment_link:
                missing_primary = _missing_payment_link_config(order.provider)
                fallback_provider_enum = (
                    PaymentProviderEnum.CLOUDPAYMENTS
                    if order.provider == PaymentProviderEnum.PRODAMUS
                    else PaymentProviderEnum.PRODAMUS
                )
                missing_fallback = _missing_payment_link_config(
                    fallback_provider_enum
                )
                logger.warning(
                    "payment_link_unavailable",
                    extra={
                        "order_id": order.id,
                        "primary_provider": order.provider.value,
                        "missing_primary": missing_primary,
                        "missing_fallback": missing_fallback,
                    },
                )
                missing_vars = (
                    ", ".join(missing_primary + missing_fallback)
                    or "секреты провайдера"
                )
                await _send_notice(
                    callback,
                    "Платёжная ссылка недоступна: не настроены ключи оплаты. "
                    f"Проверьте переменные {missing_vars}.",
                )

        screen_manager.update_state(
            callback.from_user.id,
            payment_url=payment_link.url if payment_link else None,
            payment_processing_notice=False,
            **_refresh_order_state(order),
        )
        return order


async def open_checkout_s3_with_order(
    callback: CallbackQuery,
    *,
    fallback_screen_id: str | None = None,
    missing_order_notice: str | None = None,
    use_marketing_consent: bool = False,
    run_payment_waiter: bool = False,
) -> bool:
    state_snapshot = screen_manager.update_state(callback.from_user.id)
    if state_snapshot.data.get("existing_tariff_report_found") and not state_snapshot.data.get(
        "existing_report_warning_seen"
    ):
        await _show_screen_for_callback(callback, screen_id="S15")
        return True

    order_id = _safe_int(state_snapshot.data.get("order_id"))
    if not order_id:
        if missing_order_notice:
            await _send_notice(callback, missing_order_notice)
        if fallback_screen_id:
            await _show_screen_for_callback(callback, screen_id=fallback_screen_id)
        return False

    if use_marketing_consent:
        await _show_marketing_consent_or_target_screen(callback, screen_id="S3")
    else:
        await _show_screen_for_callback(callback, screen_id="S3")

    if run_payment_waiter:
        await _maybe_run_payment_waiter(callback)
    return True


@router.callback_query()
async def handle_callbacks(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data:
        await _safe_callback_answer(callback)
        return

    await _safe_callback_processing(callback)
    screen_manager.update_state(callback.from_user.id, s4_no_inline_keyboard=False)

    if callback.data == "profile:consent:accept":
        await accept_profile_consent(callback)
        return

    if callback.data == "profile:consent:accept_without_marketing":
        await accept_profile_consent_without_marketing(callback)
        return

    if callback.data == "marketing:consent:accept":
        await accept_marketing_consent_prompt(callback)
        return

    if callback.data == "marketing:consent:skip":
        await skip_marketing_consent_prompt(callback)
        return

    if callback.data == "s2:details":
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        tariff = state_snapshot.data.get("selected_tariff")
        if tariff not in PAID_TARIFFS:
            await _show_screen_for_callback(callback, screen_id="S2")
            await _safe_callback_answer(callback)
            return
        await _show_screen_for_callback(callback, screen_id="S2_MORE")
        await _safe_callback_answer(callback)
        return

    if callback.data == "s2:details:back":
        await _show_screen_for_callback(callback, screen_id="S2")
        screen_manager.update_state(callback.from_user.id, offer_seen=True)
        await _safe_callback_answer(callback)
        return

    if callback.data == "s2:details:continue":
        await _show_marketing_consent_or_target_screen(
            callback,
            screen_id="S4",
        )
        await _safe_callback_answer(callback)
        return

    if callback.data == "s3:report_details":
        await _show_screen_for_callback(callback, screen_id="S3_INFO")
        await _safe_callback_answer(callback)
        return

    if callback.data == "s3:report_details:back":
        await _show_screen_for_callback(callback, screen_id="S3")
        await _safe_callback_answer(callback)
        return

    if callback.data.startswith("screen:"):
        screen_id = callback.data.split("screen:")[-1]
        if screen_id == "S3":
            screen_manager.update_state(
                callback.from_user.id,
                payment_processing_notice=False,
            )
        if screen_id == "S4":
            with get_session() as session:
                _refresh_profile_state(session, callback.from_user.id)
                state_snapshot = screen_manager.update_state(callback.from_user.id)
                selected_tariff = state_snapshot.data.get("selected_tariff")
                profile = state_snapshot.data.get("profile")
                if not selected_tariff and not profile:
                    await _send_notice(callback, "Сначала выберите тариф.")
                    await _show_screen_for_callback(
                        callback,
                        screen_id="S1",
                    )
                    await _safe_callback_answer(callback)
                    return
                if selected_tariff == Tariff.T0.value and not profile:
                    t0_allowed, next_available = _t0_cooldown_status(
                        session, callback.from_user.id
                    )
                    if not t0_allowed:
                        screen_manager.update_state(
                            callback.from_user.id,
                            selected_tariff=Tariff.T0.value,
                            t0_next_available=next_available,
                        )
                        await _show_screen_for_callback(
                            callback,
                            screen_id="S9",
                        )
                        await _safe_callback_answer(callback)
                        return
                order_id = _safe_int(state_snapshot.data.get("order_id"))
                if order_id:
                    order = session.get(Order, order_id)
                    if order:
                        screen_manager.update_state(
                            callback.from_user.id, **_refresh_order_state(order)
                        )
        if screen_id == "S4_EDIT":
            with get_session() as session:
                _refresh_profile_state(session, callback.from_user.id)
            state_snapshot = screen_manager.update_state(callback.from_user.id)
            if not state_snapshot.data.get("profile"):
                await _send_notice(callback, "Сначала заполните «Мои данные».")
                await _show_screen_for_callback(
                    callback,
                    screen_id="S4",
                )
                await _safe_callback_answer(callback)
                return
        if screen_id in {"S11", "S12"}:
            with get_session() as session:
                _refresh_profile_state(session, callback.from_user.id)
                _refresh_reports_list_state(session, callback.from_user.id)
                if screen_id == "S11":
                    _refresh_questionnaire_state(session, callback.from_user.id)
        if screen_id == "S3":
            state_snapshot = screen_manager.update_state(callback.from_user.id)
            selected_tariff = state_snapshot.data.get("selected_tariff")
            if selected_tariff not in PAID_TARIFFS:
                await _send_notice(callback, "Сначала выберите платный тариф.")
                await _show_screen_for_callback(
                    callback,
                    screen_id="S1",
                )
                await _safe_callback_answer(callback)
                return
            if not state_snapshot.data.get("offer_seen"):
                await _send_notice(callback, "Сначала ознакомьтесь с офертой.")
                await _show_screen_for_callback(
                    callback,
                    screen_id="S2",
                )
                await _safe_callback_answer(callback)
                return
            with get_session() as session:
                _refresh_profile_state(session, callback.from_user.id)
                _refresh_questionnaire_state(session, callback.from_user.id)
            state_snapshot = screen_manager.update_state(callback.from_user.id)
            if not state_snapshot.data.get("profile"):
                await _send_notice(callback, "Сначала заполните «Мои данные».")
                await _show_screen_for_callback(
                    callback,
                    screen_id="S4",
                )
                await start_profile_wizard(callback.message, state, callback.from_user.id)
                await _safe_callback_answer(callback)
                return
            if selected_tariff in {Tariff.T2.value, Tariff.T3.value}:
                questionnaire = state_snapshot.data.get("questionnaire") or {}
                if questionnaire.get("status") != QuestionnaireStatus.COMPLETED.value:
                    await _send_notice(callback, "Сначала заполните анкету.")
                    await _show_screen_for_callback(
                        callback,
                        screen_id="S5",
                    )
                    await _safe_callback_answer(callback)
                    return
            if state_snapshot.data.get("existing_tariff_report_found") and not state_snapshot.data.get("existing_report_warning_seen"):
                await _show_screen_for_callback(
                    callback,
                    screen_id="S15",
                )
                await _safe_callback_answer(callback)
                return
            with get_session() as session:
                order_id = _safe_int(state_snapshot.data.get("order_id"))
                order = session.get(Order, order_id) if order_id else None
                if not order:
                    await _send_notice(
                        callback,
                        "Перейдите к финальной оплате через шаг сохранения данных.",
                    )
                    target_screen_id = (
                        "S5"
                        if selected_tariff in {Tariff.T2.value, Tariff.T3.value}
                        else "S4"
                    )
                    await _show_screen_for_callback(callback, screen_id=target_screen_id)
                    await _safe_callback_answer(callback)
                    return
                screen_manager.update_state(
                    callback.from_user.id, **_refresh_order_state(order)
                )
                if order.status == OrderStatus.PAID:
                    target_screen_id = "S4"
                    if selected_tariff in {Tariff.T2.value, Tariff.T3.value}:
                        questionnaire = state_snapshot.data.get("questionnaire") or {}
                        if questionnaire.get("status") != QuestionnaireStatus.COMPLETED.value:
                            target_screen_id = "S5"
                    screen_manager.update_state(
                        callback.from_user.id,
                        profile_flow="report",
                        payment_processing_notice=False,
                        **{S4_SCENARIO_STATE_KEY: S4_SCENARIO_AFTER_PAYMENT},
                    )
                    await _show_screen_for_callback(
                        callback,
                        screen_id=target_screen_id,
                    )
                    await _safe_callback_answer(callback)
                    return
        if screen_id == "S5":
            state_snapshot = screen_manager.update_state(callback.from_user.id)
            selected_tariff = state_snapshot.data.get("selected_tariff")
            if selected_tariff not in {Tariff.T2.value, Tariff.T3.value}:
                await _send_notice(
                    callback, "Анкета доступна только для тарифов T2 и T3."
                )
                await _show_screen_for_callback(
                    callback,
                    screen_id="S1",
                )
                await _safe_callback_answer(callback)
                return
            with get_session() as session:
                _refresh_profile_state(session, callback.from_user.id)
                state_snapshot = screen_manager.update_state(callback.from_user.id)
                if not state_snapshot.data.get("profile"):
                    await _send_notice(callback, "Сначала заполните «Мои данные».")
                    await _show_screen_for_callback(
                        callback,
                        screen_id="S4",
                    )
                    await start_profile_wizard(
                        callback.message, state, callback.from_user.id
                    )
                    await _safe_callback_answer(callback)
                    return
                _refresh_questionnaire_state(session, callback.from_user.id)
        if screen_id in {"S6", "S7"}:
            state_snapshot = screen_manager.update_state(callback.from_user.id)
            selected_tariff = state_snapshot.data.get("selected_tariff")
            order_id = _safe_int(state_snapshot.data.get("order_id"))
            expected_order_id = (
                order_id
                if selected_tariff in {Tariff.T1.value, Tariff.T2.value, Tariff.T3.value}
                else None
            )
            with get_session() as session:
                job = _refresh_report_job_state(
                    session,
                    callback.from_user.id,
                    expected_tariff_value=selected_tariff,
                    expected_order_id=expected_order_id,
                )
                if (
                    job
                    and job.status == ReportJobStatus.COMPLETED
                    and screen_id == "S6"
                ):
                    screen_id = "S7"
                if (
                    job
                    and job.status != ReportJobStatus.COMPLETED
                    and screen_id == "S7"
                ):
                    screen_id = "S6"
                if screen_id == "S7":
                    _refresh_report_state(
                        session,
                        callback.from_user.id,
                        tariff_value=selected_tariff,
                    )
        if screen_id == "S3":
            opened = await open_checkout_s3_with_order(
                callback,
                fallback_screen_id=(
                    "S5"
                    if screen_manager.update_state(callback.from_user.id).data.get("selected_tariff")
                    in {Tariff.T2.value, Tariff.T3.value}
                    else "S4"
                ),
                missing_order_notice=(
                    "Перейдите к финальной оплате через шаг сохранения данных."
                ),
                use_marketing_consent=True,
                run_payment_waiter=True,
            )
            if not opened:
                await _safe_callback_answer(callback)
                return
        else:
            await _show_marketing_consent_or_target_screen(
                callback,
                screen_id=screen_id,
            )
        if screen_id == "S2":
            screen_manager.update_state(callback.from_user.id, offer_seen=True)
        await _safe_callback_answer(callback)
        return

    if callback.data == "existing_report:lk":
        with get_session() as session:
            _refresh_reports_list_state(session, callback.from_user.id)
            _refresh_profile_state(session, callback.from_user.id)
        screen_manager.update_state(
            callback.from_user.id,
            existing_tariff_report_found=False,
            existing_tariff_report_meta=None,
        )
        await _show_screen_for_callback(callback, screen_id="S11")
        await _safe_callback_answer(callback)
        return

    if callback.data == "existing_report:continue":
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        tariff = state_snapshot.data.get("selected_tariff")
        if tariff not in PAID_TARIFFS:
            await _send_notice(callback, "Сначала выберите платный тариф.")
            await _show_screen_for_callback(callback, screen_id="S1")
            await _safe_callback_answer(callback)
            return
        order = await _prepare_checkout_order(
            callback,
            tariff_value=tariff,
            force_new_order=True,
        )
        if not order:
            await _send_notice(callback, "Не удалось подготовить заказ для оплаты.")
            await _safe_callback_answer(callback)
            return
        screen_manager.update_state(
            callback.from_user.id,
            existing_tariff_report_found=False,
            existing_tariff_report_meta=None,
            existing_report_warning_seen=True,
            offer_seen=True,
            payment_processing_notice=False,
        )
        await open_checkout_s3_with_order(
            callback,
            fallback_screen_id="S4",
            missing_order_notice="Не удалось подготовить заказ для оплаты.",
        )
        await _safe_callback_answer(callback)
        return

    if callback.data.startswith("tariff:"):
        tariff = callback.data.split("tariff:")[-1]
        _reset_tariff_runtime_state(callback.from_user.id)
        existing_tariff_report_found = False
        reusable_paid_order: Order | None = None
        if tariff == Tariff.T0.value:
            with get_session() as session:
                t0_allowed, next_available = _t0_cooldown_status(
                    session, callback.from_user.id
                )
                if not t0_allowed:
                    screen_manager.update_state(
                        callback.from_user.id,
                        selected_tariff=tariff,
                        t0_next_available=next_available,
                    )
                    await _show_screen_for_callback(
                        callback,
                        screen_id="S9",
                    )
                    await _safe_callback_answer(callback)
                    return
                _refresh_profile_state(session, callback.from_user.id)
        else:
            with get_session() as session:
                reusable_paid_order = _get_reusable_paid_order(
                    session,
                    callback.from_user.id,
                    tariff,
                )
                _refresh_reports_list_state(session, callback.from_user.id)
                existing_report = _get_latest_report(
                    session,
                    callback.from_user.id,
                    tariff_value=tariff,
                )
                _store_existing_tariff_report_state(
                    callback.from_user.id,
                    existing_report,
                )
                existing_tariff_report_found = bool(existing_report)
                if reusable_paid_order:
                    screen_manager.update_state(
                        callback.from_user.id,
                        payment_url=None,
                        **_refresh_order_state(reusable_paid_order),
                    )

        screen_manager.update_state(
            callback.from_user.id,
            selected_tariff=tariff,
            profile_flow=(
                "report"
                if tariff == Tariff.T0.value or reusable_paid_order
                else None
            ),
            offer_seen=False if tariff in PAID_TARIFFS and not reusable_paid_order else True,
            existing_report_warning_seen=False,
            existing_tariff_report_found=False if reusable_paid_order else existing_tariff_report_found,
        )
        next_screen = resolve_checkout_entry_screen(
            tariff=tariff,
            reusable_paid_order=bool(reusable_paid_order),
        )
        await _show_screen_for_callback(
            callback,
            screen_id=next_screen,
        )
        if next_screen == "S2":
            screen_manager.update_state(callback.from_user.id, offer_seen=True)
        if tariff == Tariff.T0.value:
            state_snapshot = screen_manager.update_state(callback.from_user.id)
            if not state_snapshot.data.get("profile"):
                await start_profile_wizard(
                    callback.message, state, callback.from_user.id
                )
        await _safe_callback_answer(callback)
        return

    if callback.data == "payment:paid":
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        order_id = _safe_int(state_snapshot.data.get("order_id"))
        if not order_id:
            await _send_notice(callback, "Сначала выберите тариф и создайте заказ.")
            await _safe_callback_answer(callback)
            return
        with get_session() as session:
            order = session.get(Order, order_id)
            if not order:
                await _send_notice(
                    callback, "Заказ не найден. Попробуйте выбрать тариф заново."
                )
                await _safe_callback_answer(callback)
                return
            if _is_local_payment_debug_autoconfirm_enabled() and order.status != OrderStatus.PAID:
                order.status = OrderStatus.PAID
                order.paid_at = now_app_timezone()
                session.add(order)

            if order.status != OrderStatus.PAID:
                screen_manager.update_state(
                    callback.from_user.id, **_refresh_order_state(order)
                )
                await _send_notice(
                    callback,
                    "Оплата ещё не подтверждена провайдером. Без подтверждения провайдера переход к следующему экрану невозможен. Как только подтверждение поступит через webhook/проверку статуса, бот автоматически переведёт вас к следующему шагу.",
                )
                await _maybe_run_payment_waiter(callback)
                await _show_screen_for_callback(
                    callback,
                    screen_id="S3",
                )
                await _safe_callback_answer(callback)
                return
            screen_manager.update_state(
                callback.from_user.id, **_refresh_order_state(order)
            )
            _refresh_profile_state(session, callback.from_user.id)
            screen_manager.update_state(callback.from_user.id, profile_flow="report")
        await _show_screen_for_callback(
            callback,
            screen_id="S4",
        )
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        if not state_snapshot.data.get("profile"):
            await start_profile_wizard(callback.message, state, callback.from_user.id)
        await _safe_callback_answer(callback)
        return

    if callback.data == "payment:start":
        with get_session() as session:
            _refresh_profile_state(session, callback.from_user.id)
            _refresh_questionnaire_state(session, callback.from_user.id)
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        tariff = state_snapshot.data.get("selected_tariff")
        decision = resolve_checkout_transition(
            _checkout_context_from_state(state_snapshot.data),
            "payment_start",
        )
        if not decision.allowed:
            if decision.guard_reason == "paid_tariff_required":
                await _send_notice(callback, "Сначала выберите платный тариф.")
            elif decision.guard_reason == "profile_required":
                await _send_notice(callback, "Сначала заполните «Мои данные».")
            elif decision.guard_reason == "questionnaire_required":
                await _send_notice(callback, "Сначала заполните анкету.")
                await _show_screen_for_callback(callback, screen_id="S5")
            await _safe_callback_answer(callback)
            return
        if not state_snapshot.data.get("personal_data_consent_accepted"):
            await _send_notice(callback, "Нужно согласие на обработку данных.")
            await _show_screen_for_callback(
                callback,
                screen_id="S4_CONSENT",
            )
            await _safe_callback_answer(callback)
            return

        if state_snapshot.data.get("existing_tariff_report_found") and not state_snapshot.data.get(
            "existing_report_warning_seen"
        ):
            await _show_screen_for_callback(callback, screen_id="S15")
            await _safe_callback_answer(callback)
            return

        order = await _prepare_checkout_order(
            callback,
            tariff_value=tariff,
        )
        if not order:
            await _send_notice(callback, "Не удалось подготовить заказ для оплаты.")
            await _safe_callback_answer(callback)
            return
        await _show_screen_for_callback(callback, screen_id=decision.next_screen)
        await _safe_callback_answer(callback)
        return

    if callback.data == "profile:save":
        _ensure_profile_state(callback.from_user.id)
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        if not state_snapshot.data.get("profile"):
            await _send_notice(callback, "Сначала заполните «Мои данные».")
            await _safe_callback_answer(callback)
            return

        tariff = state_snapshot.data.get("selected_tariff")
        if tariff == Tariff.T0.value:
            with get_session() as session:
                t0_allowed, next_available = _t0_cooldown_status(
                    session, callback.from_user.id
                )
                if not t0_allowed:
                    screen_manager.update_state(
                        callback.from_user.id,
                        selected_tariff=Tariff.T0.value,
                        t0_next_available=next_available,
                    )
                    await _show_screen_for_callback(
                        callback,
                        screen_id="S9",
                    )
                    await _safe_callback_answer(callback)
                    return
                user = _get_or_create_user(session, callback.from_user.id, callback.from_user.username)
                if user.free_limit:
                    user.free_limit.last_t0_at = now_app_timezone()

            if not state_snapshot.data.get("personal_data_consent_accepted"):
                await _send_notice(callback, "Нужно согласие на обработку данных.")
                await _show_screen_for_callback(
                    callback,
                    screen_id="S4_CONSENT",
                )
                await _safe_callback_answer(callback)
                return

            screen_manager.update_state(
                callback.from_user.id,
                report_text=None,
                report_model=None,
                report_meta=None,
                profile_flow=None,
            )
            with get_session() as session:
                user = _get_or_create_user(session, callback.from_user.id, callback.from_user.username)
                job = _create_report_job(
                    session,
                    user=user,
                    tariff_value=tariff,
                    order_id=None,
                    chat_id=callback.message.chat.id if callback.message else None,
                )
                if not job:
                    await _send_notice(callback, "Не удалось создать задание на генерацию.")
                    await _safe_callback_answer(callback)
                    return
            await _show_screen_for_callback(callback, screen_id="S6")
            await _maybe_run_report_delay(callback)
            await _safe_callback_answer(callback)
            return

        if tariff in {Tariff.T1.value, Tariff.T2.value, Tariff.T3.value}:
            if not state_snapshot.data.get("personal_data_consent_accepted"):
                await _send_notice(callback, "Нужно согласие на обработку данных.")
                await _show_screen_for_callback(
                    callback,
                    screen_id="S4_CONSENT",
                )
                await _safe_callback_answer(callback)
                return

            screen_manager.update_state(callback.from_user.id, profile_flow=None)
            if tariff == Tariff.T1.value:
                order_id = _safe_int(state_snapshot.data.get("order_id"))
                if order_id:
                    with get_session() as session:
                        order = session.get(Order, order_id)
                        if order:
                            screen_manager.update_state(
                                callback.from_user.id,
                                **_refresh_order_state(order),
                            )
                    state_snapshot = screen_manager.update_state(callback.from_user.id)
            if tariff in {Tariff.T2.value, Tariff.T3.value}:
                with get_session() as session:
                    _refresh_questionnaire_state(session, callback.from_user.id)
                state_snapshot = screen_manager.update_state(callback.from_user.id)

            decision = resolve_checkout_transition(
                _checkout_context_from_state(state_snapshot.data),
                "profile_saved",
            )
            if not decision.allowed:
                await _send_notice(callback, "Сначала заполните «Мои данные».")
                await _safe_callback_answer(callback)
                return

            if decision.should_start_job:
                order_id = _safe_int(state_snapshot.data.get("order_id"))
                with get_session() as session:
                    user = _get_or_create_user(
                        session,
                        callback.from_user.id,
                        callback.from_user.username,
                    )
                    job = _create_report_job(
                        session,
                        user=user,
                        tariff_value=tariff,
                        order_id=order_id,
                        chat_id=callback.message.chat.id if callback.message else None,
                    )
                    if not job:
                        await _send_notice(
                            callback,
                            "Не удалось создать задание на генерацию.",
                        )
                        await _safe_callback_answer(callback)
                        return
                await _show_screen_for_callback(callback, screen_id=decision.next_screen)
                await _maybe_run_report_delay(callback)
                await _safe_callback_answer(callback)
                return

            if decision.next_screen == "S3":
                order = await _prepare_checkout_order(
                    callback,
                    tariff_value=tariff,
                )
                if not order:
                    await _send_notice(callback, "Не удалось подготовить заказ для оплаты.")
                    await _safe_callback_answer(callback)
                    return
                await open_checkout_s3_with_order(
                    callback,
                    fallback_screen_id="S4",
                    missing_order_notice="Не удалось подготовить заказ для оплаты.",
                )
                await _safe_callback_answer(callback)
                return

            await _show_screen_for_callback(callback, screen_id=decision.next_screen)
            await _safe_callback_answer(callback)
            return

        await _send_notice(callback, "Сначала выберите тариф.")
        await _show_screen_for_callback(callback, screen_id="S1")
        await _safe_callback_answer(callback)
        return

    if callback.data == "questionnaire:done":
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        existing_questionnaire = state_snapshot.data.get("questionnaire") or {}
        with get_session() as session:
            _refresh_questionnaire_state(session, callback.from_user.id)
            _refresh_profile_state(session, callback.from_user.id)
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        refreshed_questionnaire = state_snapshot.data.get("questionnaire") or {}
        if (
            refreshed_questionnaire.get("status") in {None, "empty"}
            and existing_questionnaire.get("status")
            == QuestionnaireStatus.COMPLETED.value
        ):
            state_snapshot = screen_manager.update_state(
                callback.from_user.id,
                questionnaire=existing_questionnaire,
            )
        tariff = state_snapshot.data.get("selected_tariff")
        decision = resolve_checkout_transition(
            _checkout_context_from_state(state_snapshot.data),
            "questionnaire_done",
        )
        if decision.allowed:
            if not state_snapshot.data.get("personal_data_consent_accepted"):
                await _send_notice(callback, "Нужно согласие на обработку данных.")
                await _show_screen_for_callback(
                    callback,
                    screen_id="S4_CONSENT",
                )
                await _safe_callback_answer(callback)
                return
            order = await _prepare_checkout_order(
                callback,
                tariff_value=tariff,
            )
            if not order:
                await _send_notice(callback, "Не удалось подготовить заказ для оплаты.")
                await _safe_callback_answer(callback)
                return
            if decision.next_screen == "S3":
                await open_checkout_s3_with_order(
                    callback,
                    fallback_screen_id="S5",
                    missing_order_notice="Не удалось подготовить заказ для оплаты.",
                )
                await _safe_callback_answer(callback)
                return

            await _show_screen_for_callback(callback, screen_id=decision.next_screen)
            await _safe_callback_answer(callback)
            return

        if tariff in {Tariff.T2.value, Tariff.T3.value}:
            await _send_notice(
                callback, "Анкета ещё не заполнена. Нажмите «Заполнить анкету»."
            )
            await _safe_callback_answer(callback)
            return

        if tariff == Tariff.T0.value:
            await _send_notice(callback, "Для бесплатного тарифа анкета не требуется.")
            await _show_screen_for_callback(callback, screen_id="S4")
            await _safe_callback_answer(callback)
            return

        await _send_notice(callback, "Сначала выберите тариф.")
        await _show_screen_for_callback(callback, screen_id="S1")
        await _safe_callback_answer(callback)
        return

    if callback.data == "report:retry":
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        tariff = state_snapshot.data.get("selected_tariff")
        if not tariff:
            await _send_notice(callback, "Сначала выберите тариф.")
            await _safe_callback_answer(callback)
            return
        if tariff in {Tariff.T2.value, Tariff.T3.value}:
            questionnaire = state_snapshot.data.get("questionnaire") or {}
            if questionnaire.get("status") != QuestionnaireStatus.COMPLETED.value:
                await _send_notice(callback, "Анкета ещё не заполнена.")
                await _safe_callback_answer(callback)
                return
        if tariff in {Tariff.T1.value, Tariff.T2.value, Tariff.T3.value}:
            order_id = _safe_int(state_snapshot.data.get("order_id"))
            if not order_id:
                await _send_notice(
                    callback, "Сначала выберите тариф и завершите оплату."
                )
                await _safe_callback_answer(callback)
                return
            with get_session() as session:
                order = session.get(Order, order_id)
                if not order or order.status != OrderStatus.PAID:
                    if order:
                        screen_manager.update_state(
                            callback.from_user.id, **_refresh_order_state(order)
                        )
                    await _send_notice(callback, "Оплата ещё не подтверждена.")
                    await _show_screen_for_callback(
                        callback,
                        screen_id="S3",
                    )
                    await _safe_callback_answer(callback)
                    return
        with get_session() as session:
            user = _get_or_create_user(session, callback.from_user.id, callback.from_user.username)
            job = _refresh_report_job_state(session, callback.from_user.id)
            if job and job.status == ReportJobStatus.COMPLETED:
                _refresh_report_state(
                    session,
                    callback.from_user.id,
                    tariff_value=tariff,
                )
                await _ensure_report_delivery(callback, "S7")
                await _safe_callback_answer(callback)
                return
            if job and job.status == ReportJobStatus.FAILED:
                _requeue_report_job(
                    session, telegram_user_id=callback.from_user.id, job=job
                )
            if not job:
                _create_report_job(
                    session,
                    user=user,
                    tariff_value=tariff,
                    order_id=_safe_int(state_snapshot.data.get("order_id")),
                    chat_id=callback.message.chat.id if callback.message else None,
                )
        await _show_screen_for_callback(
            callback,
            screen_id="S6",
        )
        await _maybe_run_report_delay(callback)
        await _safe_callback_answer(callback)
        return

    if callback.data.startswith("report:view:"):
        report_id = _safe_int(callback.data.split("report:view:")[-1])
        if not report_id:
            await _send_notice(
                callback, "Не удалось открыть отчёт. Попробуйте выбрать его ещё раз."
            )
            await _safe_callback_answer(callback)
            return
        with get_session() as session:
            report = _get_report_for_user(session, callback.from_user.id, report_id)
            if not report:
                await _send_notice(
                    callback, "Отчёт не найден. Обновите список в кабинете."
                )
                await _show_reports_list_with_refresh(callback)
                await _safe_callback_answer(callback)
                return
            screen_manager.update_state(
                callback.from_user.id,
                report_text=report.report_text,
                report_meta=_report_meta_payload(report),
            )
        await _ensure_report_delivery(callback, "S13")
        await _safe_callback_answer(callback)
        return

    if (
        callback.data.startswith("report:delete:")
        and callback.data != "report:delete:confirm"
        and callback.data != "report:delete:confirm_all"
    ):
        report_id = _safe_int(callback.data.split("report:delete:")[-1])
        if not report_id:
            await _send_notice(callback, "Не удалось выбрать отчёт для удаления.")
            await _safe_callback_answer(callback)
            return
        with get_session() as session:
            report = _get_report_for_user(session, callback.from_user.id, report_id)
            if not report:
                await _send_notice(callback, "Отчёт не найден. Обновите список.")
                await _show_reports_list_with_refresh(callback)
                await _safe_callback_answer(callback)
                return
            screen_manager.update_state(
                callback.from_user.id,
                report_meta=_report_meta_payload(report),
                report_text=report.report_text,
                report_delete_scope="single",
            )
        await _show_screen_for_callback(
            callback,
            screen_id="S14",
        )
        await _safe_callback_answer(callback)
        return

    if callback.data == "report:delete_all":
        with get_session() as session:
            _refresh_reports_list_state(session, callback.from_user.id)
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        reports = state_snapshot.data.get("reports") or []
        if not reports:
            await _send_notice(callback, "Список отчётов уже пуст.")
            await _show_screen_for_callback(
                callback,
                screen_id="S12",
            )
            await _safe_callback_answer(callback)
            return
        screen_manager.update_state(
            callback.from_user.id,
            report_delete_scope="all",
            report_meta=None,
            report_text=None,
        )
        await _show_screen_for_callback(
            callback,
            screen_id="S14",
        )
        await _safe_callback_answer(callback)
        return

    if callback.data == "report:delete:confirm":
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        report_meta = state_snapshot.data.get("report_meta") or {}
        report_id = _safe_int(report_meta.get("id"))
        if not report_id:
            await _send_notice(
                callback, "Не удалось удалить отчёт. Попробуйте ещё раз."
            )
            await _safe_callback_answer(callback)
            return
        report_deleted = False
        with get_session() as session:
            report = _get_report_for_user(session, callback.from_user.id, report_id)
            if not report:
                await _send_notice(callback, "Отчёт уже удалён или недоступен.")
            else:
                report_deleted = _delete_report_with_assets(session, report)
                if not report_deleted:
                    await _send_notice(callback, "Не удалось удалить отчёт. Попробуйте ещё раз.")
            _refresh_reports_list_state(session, callback.from_user.id)
        screen_manager.update_state(
            callback.from_user.id,
            report_text=None,
            report_meta=None,
            report_delete_scope=None,
        )
        if report_deleted:
            await _send_notice(callback, "Отчёт удалён.")
        await _show_screen_for_callback(
            callback,
            screen_id="S12",
        )
        await _safe_callback_answer(callback)
        return

    if callback.data == "report:delete:confirm_all":
        deleted_reports_count = 0
        with get_session() as session:
            reports = _get_reports_for_user(session, callback.from_user.id)
            for report in reports:
                if _delete_report_with_assets(session, report):
                    deleted_reports_count += 1
            _refresh_reports_list_state(session, callback.from_user.id)
        screen_manager.update_state(
            callback.from_user.id,
            report_text=None,
            report_meta=None,
            report_delete_scope=None,
        )
        if deleted_reports_count:
            await _send_notice(callback, "Все отчёты удалены.")
        else:
            await _send_notice(callback, "Список отчётов уже пуст или временно недоступен для удаления.")
        await _show_screen_for_callback(
            callback,
            screen_id="S12",
        )
        await _safe_callback_answer(callback)
        return

    if callback.data.startswith("report:pdf:"):
        report_id = _safe_int(callback.data.split("report:pdf:")[-1])
        if not report_id:
            await _send_notice(
                callback, "Не удалось сформировать PDF. Попробуйте ещё раз."
            )
            await _safe_callback_answer(callback)
            return
        with get_session() as session:
            report = _get_report_for_user(session, callback.from_user.id, report_id)
            if not report:
                await _send_notice(
                    callback, "Отчёт не найден. Попробуйте выбрать другой."
                )
                await _safe_callback_answer(callback)
                return
            report_meta = _get_report_pdf_meta(report)
            pdf_bytes = _get_report_pdf_bytes(session, report)
        if not await _send_report_pdf(
            callback.bot,
            callback.message.chat.id,
            report_meta,
            pdf_bytes=pdf_bytes,
            username=callback.from_user.username,
            user_id=callback.from_user.id,
        ):
            await _send_notice(
                callback, "Не удалось сформировать PDF. Попробуйте ещё раз чуть позже."
            )
        await _safe_callback_answer(callback)
        return

    if callback.data == "report:pdf":
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        report_id = None
        with get_session() as session:
            report = _get_latest_report(
                session,
                callback.from_user.id,
                tariff_value=state_snapshot.data.get("selected_tariff"),
            )
            if not report:
                await _send_notice(
                    callback, "PDF будет доступен после генерации отчёта."
                )
                await _safe_callback_answer(callback)
                return
            report_meta = _get_report_pdf_meta(report)
            report_id = report_meta.get("id") if report_meta else None
            pdf_bytes = _get_report_pdf_bytes(session, report)
        if report_id is None or not await _send_report_pdf(
            callback.bot,
            callback.message.chat.id,
            report_meta,
            pdf_bytes=pdf_bytes,
            username=callback.from_user.username,
            user_id=callback.from_user.id,
        ):
            await _send_notice(
                callback, "Не удалось сформировать PDF. Попробуйте ещё раз чуть позже."
            )
        await _safe_callback_answer(callback)
        return

    thread_feedback_id = _extract_quick_reply_thread_id(callback.data)
    if thread_feedback_id is not None:
        if not thread_feedback_id:
            await _send_notice(
                callback, "Не удалось открыть быстрый ответ. Попробуйте ещё раз."
            )
            await _safe_callback_answer(callback)
            return
        screen_manager.update_state(
            callback.from_user.id,
            support_thread_feedback_id=thread_feedback_id,
            feedback_text=None,
        )
        await _show_screen_for_callback(
            callback,
            screen_id="S8",
        )
        await _safe_callback_answer(callback)
        return

    if callback.data == "feedback:send":
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        feedback_text = state_snapshot.data.get("feedback_text") or ""

        status = await _submit_feedback(
            callback.bot,
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            feedback_text=feedback_text,
        )

        if status == FeedbackStatus.SENT:
            await _send_notice(callback, FEEDBACK_SENT_NOTICE)
        else:
            await _send_notice(
                callback,
                "Не удалось отправить сообщение в админку. Попробуйте позже.",
            )

        if status == FeedbackStatus.SENT:
            screen_manager.update_state(callback.from_user.id, feedback_text=None)
        await _safe_callback_answer(callback)
        return

    await _safe_callback_answer(callback)
