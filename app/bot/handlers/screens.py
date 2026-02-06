from __future__ import annotations

from datetime import datetime, timedelta, timezone
import asyncio
import logging
from typing import Any

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy import select, func

from app.bot.questionnaire.config import load_questionnaire_config
from app.bot.screens import build_report_wait_message
from app.bot.handlers.profile import start_profile_wizard
from app.bot.handlers.screen_manager import screen_manager
from app.core.config import settings
from app.core.llm_key_store import resolve_llm_keys
from app.core.pdf_service import pdf_service
from app.core.monitoring import send_monitoring_event
from app.core.report_service import report_service
from app.db.models import (
    FreeLimit,
    Order,
    OrderStatus,
    PaymentProvider as PaymentProviderEnum,
    QuestionnaireResponse,
    QuestionnaireStatus,
    Report,
    Tariff,
    User,
    UserProfile,
    FeedbackMessage,
    FeedbackStatus,
)
from app.db.session import get_session
from app.payments import get_payment_provider


router = Router()
logger = logging.getLogger(__name__)

TARIFF_PRICES = {
    Tariff.T1: 560,
    Tariff.T2: 2190,
    Tariff.T3: 5930,
}

PAID_TARIFFS = {Tariff.T1.value, Tariff.T2.value, Tariff.T3.value}


def _safe_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _run_report_delay(bot: Bot, chat_id: int, user_id: int) -> None:
    delay_seconds = settings.report_delay_seconds
    if delay_seconds <= 0:
        return
    state = screen_manager.update_state(user_id)
    if not state.message_ids:
        await asyncio.sleep(delay_seconds)
        return
    message_id = state.message_ids[-1]
    content = screen_manager.render_screen("S6", user_id, state.data)
    frames = ["⏳", "⌛", "🔄", "✨"]
    for remaining in range(delay_seconds, 0, -1):
        frame = frames[remaining % len(frames)]
        text = build_report_wait_message(remaining, frame)
        try:
            await bot.edit_message_text(
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
            await asyncio.sleep(delay_seconds)
            return
        await asyncio.sleep(1)


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


async def _ensure_report_delivery(callback: CallbackQuery, screen_id: str) -> bool:
    delivered = await screen_manager.show_screen(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
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
    delivered = await screen_manager.show_screen(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        screen_id=screen_id,
    )
    if not delivered:
        logger.warning(
            "report_delivery_failed",
            extra={"user_id": callback.from_user.id, "screen_id": screen_id},
        )
    return delivered


async def _generate_report_with_retry(
    callback: CallbackQuery,
    *,
    user_id: int,
    state: dict[str, Any],
    attempts: int = 2,
) -> Any | None:
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            report = await report_service.generate_report(user_id=user_id, state=state)
        except Exception as exc:
            logger.warning(
                "report_generate_failed",
                extra={
                    "user_id": callback.from_user.id,
                    "attempt": attempt,
                    "error": str(exc),
                },
            )
            report = None
        if report:
            return report
        if attempt < attempts and callback.message:
            await screen_manager.send_ephemeral_message(
                callback.message,
                "Извините, произошла техническая заминка при подготовке отчёта. Сейчас повторю запрос.",
                user_id=callback.from_user.id,
            )
            await asyncio.sleep(1)
    await send_monitoring_event(
        "report_generate_failed",
        {
            "user_id": callback.from_user.id,
            "attempts": attempts,
            "screen_id": screen_manager.update_state(callback.from_user.id).screen_id,
        },
    )
    return None


async def _send_notice(callback: CallbackQuery, text: str, **kwargs: Any) -> None:
    await screen_manager.send_ephemeral_message(
        callback.message,
        text,
        user_id=callback.from_user.id,
        **kwargs,
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
        if not settings.prodamus_status_url:
            missing.append("PRODAMUS_STATUS_URL")
        if not settings.prodamus_secret:
            missing.append("PRODAMUS_SECRET")
    elif provider == PaymentProviderEnum.CLOUDPAYMENTS:
        if not settings.cloudpayments_public_id:
            missing.append("CLOUDPAYMENTS_PUBLIC_ID")
        if not settings.cloudpayments_api_secret:
            missing.append("CLOUDPAYMENTS_API_SECRET")
    return missing


async def _notify_llm_unavailable(callback: CallbackQuery) -> bool:
    gemini_keys = resolve_llm_keys(
        provider="gemini",
        primary_key=settings.gemini_api_key,
        extra_keys=settings.gemini_api_keys,
    )
    openai_keys = resolve_llm_keys(
        provider="openai",
        primary_key=settings.openai_api_key,
        extra_keys=settings.openai_api_keys,
    )
    if gemini_keys or openai_keys:
        return True
    logger.warning(
        "llm_keys_missing",
        extra={
            "user_id": callback.from_user.id,
            "keys": [
                "GEMINI_API_KEY",
                "GEMINI_API_KEYS",
                "OPENAI_API_KEY",
                "OPENAI_API_KEYS",
            ],
        },
    )
    return False


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


def _get_or_create_user(session, telegram_user_id: int) -> User:
    user = session.execute(
        select(User).where(User.telegram_user_id == telegram_user_id)
    ).scalar_one_or_none()
    if user:
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

    user = User(telegram_user_id=telegram_user_id)
    session.add(user)
    session.flush()
    free_limit = FreeLimit(user_id=user.id)
    session.add(free_limit)
    user.free_limit = free_limit
    return user


def _profile_payload(profile: UserProfile | None) -> dict[str, dict[str, str | None] | None]:
    if not profile:
        return {"profile": None}
    return {
        "profile": {
            "name": profile.name,
            "birth_date": profile.birth_date,
            "birth_time": profile.birth_time,
            "birth_place": {
                "city": profile.birth_place_city,
                "region": profile.birth_place_region,
                "country": profile.birth_place_country,
            },
        }
    }


def _refresh_profile_state(session, telegram_user_id: int) -> None:
    user = _get_or_create_user(session, telegram_user_id)
    screen_manager.update_state(telegram_user_id, **_profile_payload(user.profile))


def _t0_cooldown_status(session, telegram_user_id: int) -> tuple[bool, str | None]:
    user = _get_or_create_user(session, telegram_user_id)
    free_limit = user.free_limit
    last_t0_at = free_limit.last_t0_at if free_limit else None
    if last_t0_at and last_t0_at.tzinfo is None:
        last_t0_at = last_t0_at.replace(tzinfo=timezone.utc)
    cooldown = timedelta(hours=settings.free_t0_cooldown_hours)
    now = datetime.now(timezone.utc)
    if last_t0_at and now < last_t0_at + cooldown:
        next_available = last_t0_at + cooldown
        return False, next_available.strftime("%Y-%m-%d %H:%M UTC")
    return True, None


def _refresh_questionnaire_state(session, telegram_user_id: int) -> None:
    config = load_questionnaire_config()
    response = session.execute(
        select(QuestionnaireResponse).where(
            QuestionnaireResponse.user_id == _get_or_create_user(session, telegram_user_id).id,
            QuestionnaireResponse.questionnaire_version == config.version,
        )
    ).scalar_one_or_none()
    answers = response.answers if response and response.answers else {}
    screen_manager.update_state(
        telegram_user_id,
        questionnaire={
            "version": config.version,
            "status": response.status.value if response else "empty",
            "answers": answers,
            "current_question_id": response.current_question_id if response else None,
            "answered_count": len(answers),
            "total_questions": len(config.questions),
            "completed_at": response.completed_at.isoformat() if response and response.completed_at else None,
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
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _refresh_reports_list_state(session, telegram_user_id: int, *, limit: int = 10) -> None:
    user = _get_user(session, telegram_user_id)
    if not user:
        screen_manager.update_state(
            telegram_user_id,
            reports=[],
            reports_total=0,
        )
        return
    total = session.execute(
        select(func.count(Report.id)).where(Report.user_id == user.id)
    ).scalar() or 0
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
            report.tariff.value if isinstance(report.tariff, Tariff) else str(report.tariff)
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


def _get_report_for_user(
    session, telegram_user_id: int, report_id: int
) -> Report | None:
    user = _get_user(session, telegram_user_id)
    if not user:
        return None
    return session.execute(
        select(Report).where(Report.user_id == user.id, Report.id == report_id)
    ).scalar_one_or_none()


def _report_meta_payload(report: Report) -> dict[str, str]:
    tariff_value = report.tariff.value if isinstance(report.tariff, Tariff) else str(report.tariff)
    return {
        "id": str(report.id),
        "tariff": tariff_value,
        "created_at": _format_report_created_at(report.created_at),
    }


def _get_report_pdf_bytes(session, report: Report) -> bytes | None:
    pdf_bytes = None
    if report.pdf_storage_key:
        pdf_bytes = pdf_service.load_pdf(report.pdf_storage_key)
    if pdf_bytes is None:
        try:
            pdf_bytes = pdf_service.generate_pdf(report.report_text or "")
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
    created_at_value = report.created_at if isinstance(report.created_at, datetime) else None
    return {
        "id": report_id,
        "tariff": tariff_value,
        "created_at": created_at_value,
    }


def _build_report_pdf_filename(report_meta: dict | None, username: str | None) -> str:
    raw_username = str(username) if username else "unknown"
    display_username = (
        raw_username if raw_username.startswith("@") else f"@{raw_username}"
    )
    tariff_value = "tariff"
    created_at_value = "unknown-time"
    report_id = "report"
    if report_meta:
        report_id = str(report_meta.get("id") or report_id)
        tariff_value = str(report_meta.get("tariff") or tariff_value)
        created_at = report_meta.get("created_at")
        if isinstance(created_at, datetime):
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            created_at_value = created_at.astimezone(timezone.utc).strftime(
                "%Y%m%d-%H%M%S"
            )
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
    filename = _build_report_pdf_filename(report_meta, username)
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
        amount=TARIFF_PRICES[tariff],
        currency="RUB",
        provider=_get_payment_provider(),
        status=OrderStatus.CREATED,
    )
    session.add(order)
    session.flush()
    return order


def _refresh_order_state(order: Order) -> dict[str, str]:
    return {
        "order_id": str(order.id),
        "order_status": order.status.value,
        "order_amount": str(order.amount),
        "order_currency": order.currency,
    }


@router.callback_query()
async def handle_callbacks(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data:
        await _safe_callback_answer(callback)
        return

    await _safe_callback_processing(callback)

    if callback.data.startswith("screen:"):
        screen_id = callback.data.split("screen:")[-1]
        if screen_id == "S4":
            with get_session() as session:
                _refresh_profile_state(session, callback.from_user.id)
                state_snapshot = screen_manager.update_state(callback.from_user.id)
                selected_tariff = state_snapshot.data.get("selected_tariff")
                profile = state_snapshot.data.get("profile")
                if not selected_tariff and not profile:
                    await _send_notice(callback, "Сначала выберите тариф.")
                    await screen_manager.show_screen(
                        bot=callback.bot,
                        chat_id=callback.message.chat.id,
                        user_id=callback.from_user.id,
                        screen_id="S1",
                    )
                    await _safe_callback_answer(callback)
                    return
                if selected_tariff in PAID_TARIFFS and not profile:
                    order_id = _safe_int(state_snapshot.data.get("order_id"))
                    order = session.get(Order, order_id) if order_id else None
                    if order:
                        screen_manager.update_state(
                            callback.from_user.id, **_refresh_order_state(order)
                        )
                    if not order or order.status != OrderStatus.PAID:
                        await _send_notice(callback, 
                            "Сначала подтвердите оплату, чтобы заполнить «Мои данные»."
                        )
                        await screen_manager.show_screen(
                            bot=callback.bot,
                            chat_id=callback.message.chat.id,
                            user_id=callback.from_user.id,
                            screen_id="S3",
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
                        await screen_manager.show_screen(
                            bot=callback.bot,
                            chat_id=callback.message.chat.id,
                            user_id=callback.from_user.id,
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
                await screen_manager.show_screen(
                    bot=callback.bot,
                    chat_id=callback.message.chat.id,
                    user_id=callback.from_user.id,
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
                await screen_manager.show_screen(
                    bot=callback.bot,
                    chat_id=callback.message.chat.id,
                    user_id=callback.from_user.id,
                    screen_id="S1",
                )
                await _safe_callback_answer(callback)
                return
            if not state_snapshot.data.get("offer_seen"):
                await _send_notice(callback, "Сначала ознакомьтесь с офертой.")
                await screen_manager.show_screen(
                    bot=callback.bot,
                    chat_id=callback.message.chat.id,
                    user_id=callback.from_user.id,
                    screen_id="S2",
                )
                await _safe_callback_answer(callback)
                return
            if not state_snapshot.data.get("order_id"):
                await _send_notice(callback, 
                    "Сначала выберите тариф и создайте заказ."
                )
                await screen_manager.show_screen(
                    bot=callback.bot,
                    chat_id=callback.message.chat.id,
                    user_id=callback.from_user.id,
                    screen_id="S1",
                )
                await _safe_callback_answer(callback)
                return
        if screen_id == "S5":
            state_snapshot = screen_manager.update_state(callback.from_user.id)
            selected_tariff = state_snapshot.data.get("selected_tariff")
            if selected_tariff not in {Tariff.T2.value, Tariff.T3.value}:
                await _send_notice(callback, 
                    "Анкета доступна только для тарифов T2 и T3."
                )
                await screen_manager.show_screen(
                    bot=callback.bot,
                    chat_id=callback.message.chat.id,
                    user_id=callback.from_user.id,
                    screen_id="S1",
                )
                await _safe_callback_answer(callback)
                return
            with get_session() as session:
                order_id = _safe_int(state_snapshot.data.get("order_id"))
                if not order_id:
                    await _send_notice(callback, 
                        "Сначала выберите тариф и завершите оплату."
                    )
                    await screen_manager.show_screen(
                        bot=callback.bot,
                        chat_id=callback.message.chat.id,
                        user_id=callback.from_user.id,
                        screen_id="S3",
                    )
                    await _safe_callback_answer(callback)
                    return
                order = session.get(Order, order_id)
                if order:
                    screen_manager.update_state(
                        callback.from_user.id, **_refresh_order_state(order)
                    )
                if not order or order.status != OrderStatus.PAID:
                    await _send_notice(callback, 
                        "Сначала подтвердите оплату, чтобы перейти к анкете."
                    )
                    await screen_manager.show_screen(
                        bot=callback.bot,
                        chat_id=callback.message.chat.id,
                        user_id=callback.from_user.id,
                        screen_id="S3",
                    )
                    await _safe_callback_answer(callback)
                    return
                _refresh_profile_state(session, callback.from_user.id)
                state_snapshot = screen_manager.update_state(callback.from_user.id)
                if not state_snapshot.data.get("profile"):
                    await _send_notice(callback, "Сначала заполните «Мои данные».")
                    await screen_manager.show_screen(
                        bot=callback.bot,
                        chat_id=callback.message.chat.id,
                        user_id=callback.from_user.id,
                        screen_id="S4",
                    )
                    await start_profile_wizard(
                        callback.message, state, callback.from_user.id
                    )
                    await _safe_callback_answer(callback)
                    return
                _refresh_questionnaire_state(session, callback.from_user.id)
        if screen_id == "S7":
            state_snapshot = screen_manager.update_state(callback.from_user.id)
            with get_session() as session:
                _refresh_report_state(
                    session,
                    callback.from_user.id,
                    tariff_value=state_snapshot.data.get("selected_tariff"),
                )
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id=screen_id,
        )
        if screen_id == "S2":
            screen_manager.update_state(callback.from_user.id, offer_seen=True)
        await _safe_callback_answer(callback)
        return

    if callback.data.startswith("tariff:"):
        tariff = callback.data.split("tariff:")[-1]
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
                    await screen_manager.show_screen(
                        bot=callback.bot,
                        chat_id=callback.message.chat.id,
                        user_id=callback.from_user.id,
                        screen_id="S9",
                    )
                    await _safe_callback_answer(callback)
                    return
                _refresh_profile_state(session, callback.from_user.id)
        else:
            with get_session() as session:
                user = _get_or_create_user(session, callback.from_user.id)
                order = _create_order(session, user, Tariff(tariff))
                payment_link = None
                if settings.payment_enabled:
                    provider = get_payment_provider(order.provider.value)
                    payment_link = provider.create_payment_link(order, user=user)
                    if not payment_link and order.provider == PaymentProviderEnum.PRODAMUS:
                        fallback_provider = get_payment_provider(
                            PaymentProviderEnum.CLOUDPAYMENTS.value
                        )
                        payment_link = fallback_provider.create_payment_link(order, user=user)
                        if payment_link:
                            order.provider = PaymentProviderEnum.CLOUDPAYMENTS
                            provider = fallback_provider
                            session.add(order)
                    if not payment_link:
                        missing_primary = _missing_payment_link_config(order.provider)
                        fallback_provider_enum = (
                            PaymentProviderEnum.CLOUDPAYMENTS
                            if order.provider == PaymentProviderEnum.PRODAMUS
                            else PaymentProviderEnum.PRODAMUS
                        )
                        missing_fallback = _missing_payment_link_config(fallback_provider_enum)
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
                            ", ".join(missing_primary + missing_fallback) or "секреты провайдера"
                        )
                        await _send_notice(callback, 
                            "Платёжная ссылка недоступна: не настроены ключи оплаты. "
                            f"Проверьте переменные {missing_vars}."
                        )
                screen_manager.update_state(
                    callback.from_user.id,
                    selected_tariff=tariff,
                    payment_url=payment_link.url if payment_link else None,
                    **_refresh_order_state(order),
                )

        screen_manager.update_state(
            callback.from_user.id,
            selected_tariff=tariff,
            profile_flow="report" if tariff == Tariff.T0.value else None,
            offer_seen=False if tariff in PAID_TARIFFS else True,
        )
        next_screen = "S4" if tariff == Tariff.T0.value else "S2"
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
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
                await _send_notice(callback, "Заказ не найден. Попробуйте выбрать тариф заново.")
                await _safe_callback_answer(callback)
                return
            if not settings.payment_enabled:
                if order.status != OrderStatus.PAID:
                    order.status = OrderStatus.PAID
                    order.paid_at = datetime.now(timezone.utc)
                    session.add(order)
            elif order.status != OrderStatus.PAID:
                missing_status = _missing_payment_status_config(order.provider)
                if missing_status:
                    logger.warning(
                        "payment_status_config_missing",
                        extra={
                            "order_id": order.id,
                            "provider": order.provider.value,
                            "missing": missing_status,
                        },
                    )
                    await _send_notice(callback, 
                        "Проверка оплаты недоступна: не настроены ключи платёжного провайдера. "
                        f"Добавьте {', '.join(missing_status)}."
                    )
                    await screen_manager.show_screen(
                        bot=callback.bot,
                        chat_id=callback.message.chat.id,
                        user_id=callback.from_user.id,
                        screen_id="S3",
                    )
                    await _safe_callback_answer(callback)
                    return
                provider = get_payment_provider(order.provider.value)
                result = provider.check_payment_status(order)
                if result and result.is_paid:
                    order.status = OrderStatus.PAID
                    order.paid_at = datetime.now(timezone.utc)
                    if result.provider_payment_id:
                        order.provider_payment_id = result.provider_payment_id
                    order.provider = PaymentProviderEnum(provider.provider.value)
                    session.add(order)
                else:
                    screen_manager.update_state(
                        callback.from_user.id, **_refresh_order_state(order)
                    )
                    await _send_notice(callback, 
                        "Оплата ещё не подтверждена. Мы проверим статус и сообщим, когда всё будет готово."
                    )
                    await screen_manager.show_screen(
                        bot=callback.bot,
                        chat_id=callback.message.chat.id,
                        user_id=callback.from_user.id,
                        screen_id="S3",
                    )
                    await _safe_callback_answer(callback)
                    return
            screen_manager.update_state(callback.from_user.id, **_refresh_order_state(order))
            _refresh_profile_state(session, callback.from_user.id)
            screen_manager.update_state(callback.from_user.id, profile_flow="report")
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id="S4",
        )
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        if not state_snapshot.data.get("profile"):
            await start_profile_wizard(callback.message, state, callback.from_user.id)
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
        if tariff in {Tariff.T1.value, Tariff.T2.value, Tariff.T3.value}:
            order_id = _safe_int(state_snapshot.data.get("order_id"))
            if not order_id:
                await _send_notice(callback, "Сначала выберите тариф и завершите оплату.")
                await _safe_callback_answer(callback)
                return
            with get_session() as session:
                order = session.get(Order, order_id)
                if not order or order.status != OrderStatus.PAID:
                    if order:
                        screen_manager.update_state(
                            callback.from_user.id, **_refresh_order_state(order)
                        )
                    await _send_notice(callback, 
                        "Оплата ещё не подтверждена. Доступ к генерации откроется после статуса paid."
                    )
                    await screen_manager.show_screen(
                        bot=callback.bot,
                        chat_id=callback.message.chat.id,
                        user_id=callback.from_user.id,
                        screen_id="S3",
                    )
                    await _safe_callback_answer(callback)
                    return
                existing_report = _get_report_for_order(session, order_id)
                if existing_report:
                    screen_manager.update_state(
                        callback.from_user.id,
                        report_text=existing_report.report_text,
                        report_model=existing_report.model_used.value
                        if existing_report.model_used
                        else None,
                    )
                    if settings.report_delay_seconds > 0:
                        await screen_manager.show_screen(
                            bot=callback.bot,
                            chat_id=callback.message.chat.id,
                            user_id=callback.from_user.id,
                            screen_id="S6",
                        )
                        await _run_report_delay(
                            callback.bot,
                            callback.message.chat.id,
                            callback.from_user.id,
                        )
                    await _ensure_report_delivery(callback, "S7")
                    report_meta = _get_report_pdf_meta(existing_report)
                    pdf_bytes = _get_report_pdf_bytes(session, existing_report)
                    if not await _send_report_pdf(
                        callback.bot,
                        callback.message.chat.id,
                        report_meta,
                        pdf_bytes=pdf_bytes,
                        username=callback.from_user.username,
                        user_id=callback.from_user.id,
                    ):
                        await _send_notice(
                            callback,
                            "PDF уже сформирован ранее. "
                            "Вы можете попробовать кнопку «Выгрузить PDF»."
                        )
                    await _safe_callback_answer(callback)
                    return
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
                    await screen_manager.show_screen(
                        bot=callback.bot,
                        chat_id=callback.message.chat.id,
                        user_id=callback.from_user.id,
                        screen_id="S9",
                    )
                    await _safe_callback_answer(callback)
                    return
                user = _get_or_create_user(session, callback.from_user.id)
                if user.free_limit:
                    user.free_limit.last_t0_at = datetime.now(timezone.utc)
        screen_manager.update_state(callback.from_user.id, profile_flow=None)
        next_screen = "S5" if tariff in {Tariff.T2.value, Tariff.T3.value} else "S6"
        if next_screen == "S6":
            await screen_manager.show_screen(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                user_id=callback.from_user.id,
                screen_id="S6",
            )
            await _safe_callback_answer(callback)
            if not await _notify_llm_unavailable(callback):
                await screen_manager.show_screen(
                    bot=callback.bot,
                    chat_id=callback.message.chat.id,
                    user_id=callback.from_user.id,
                    screen_id="S10",
                )
                await _safe_callback_answer(callback)
                return
            with get_session() as session:
                user = _get_or_create_user(session, callback.from_user.id)
                user_id = user.id
            report = await _generate_report_with_retry(
                callback,
                user_id=user_id,
                state=screen_manager.update_state(callback.from_user.id).data,
            )
            if report:
                screen_manager.update_state(
                    callback.from_user.id,
                    report_text=report.text,
                    report_provider=report.provider,
                    report_model=report.model,
                )
                await _run_report_delay(
                    callback.bot,
                    callback.message.chat.id,
                    callback.from_user.id,
                )
                await _ensure_report_delivery(callback, "S7")
                with get_session() as session:
                    latest_report = _get_latest_report(
                        session,
                        callback.from_user.id,
                        tariff_value=tariff,
                    )
                    report_meta = _get_report_pdf_meta(latest_report)
                    latest_report_id = report_meta.get("id") if report_meta else None
                    pdf_bytes = (
                        _get_report_pdf_bytes(session, latest_report)
                        if latest_report
                        else None
                    )
                if latest_report_id and not await _send_report_pdf(
                    callback.bot,
                    callback.message.chat.id,
                    report_meta,
                    pdf_bytes=pdf_bytes,
                    username=callback.from_user.username,
                    user_id=callback.from_user.id,
                ):
                    await _send_notice(
                        callback,
                        "Не удалось сформировать PDF автоматически. "
                        "Вы можете попробовать кнопку «Выгрузить PDF»."
                    )
            else:
                await screen_manager.show_screen(
                    bot=callback.bot,
                    chat_id=callback.message.chat.id,
                    user_id=callback.from_user.id,
                    screen_id="S10",
                )
        else:
            with get_session() as session:
                _refresh_questionnaire_state(session, callback.from_user.id)
            await screen_manager.show_screen(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                user_id=callback.from_user.id,
                screen_id=next_screen,
            )
        await _safe_callback_answer(callback)
        return

    if callback.data == "questionnaire:done":
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        tariff = state_snapshot.data.get("selected_tariff")
        if tariff in {Tariff.T2.value, Tariff.T3.value}:
            order_id = _safe_int(state_snapshot.data.get("order_id"))
            if not order_id:
                await _send_notice(callback, "Сначала выберите тариф и завершите оплату.")
                await _safe_callback_answer(callback)
                return
            with get_session() as session:
                order = session.get(Order, order_id)
                if not order or order.status != OrderStatus.PAID:
                    if order:
                        screen_manager.update_state(
                            callback.from_user.id, **_refresh_order_state(order)
                        )
                    await _send_notice(callback, 
                        "Оплата ещё не подтверждена. Генерация будет доступна после статуса paid."
                    )
                    await screen_manager.show_screen(
                        bot=callback.bot,
                        chat_id=callback.message.chat.id,
                        user_id=callback.from_user.id,
                        screen_id="S3",
                    )
                    await _safe_callback_answer(callback)
                    return
                existing_report = _get_report_for_order(session, order_id)
                if existing_report:
                    screen_manager.update_state(
                        callback.from_user.id,
                        report_text=existing_report.report_text,
                        report_model=existing_report.model_used.value
                        if existing_report.model_used
                        else None,
                    )
                    if settings.report_delay_seconds > 0:
                        await screen_manager.show_screen(
                            bot=callback.bot,
                            chat_id=callback.message.chat.id,
                            user_id=callback.from_user.id,
                            screen_id="S6",
                        )
                        await _run_report_delay(
                            callback.bot,
                            callback.message.chat.id,
                            callback.from_user.id,
                        )
                    await _ensure_report_delivery(callback, "S7")
                    report_meta = _get_report_pdf_meta(existing_report)
                    pdf_bytes = _get_report_pdf_bytes(session, existing_report)
                    if not await _send_report_pdf(
                        callback.bot,
                        callback.message.chat.id,
                        report_meta,
                        pdf_bytes=pdf_bytes,
                        username=callback.from_user.username,
                        user_id=callback.from_user.id,
                    ):
                        await _send_notice(
                            callback,
                            "PDF уже сформирован ранее. "
                            "Вы можете попробовать кнопку «Выгрузить PDF»."
                        )
                    await _safe_callback_answer(callback)
                    return
            questionnaire = state_snapshot.data.get("questionnaire") or {}
            if questionnaire.get("status") != QuestionnaireStatus.COMPLETED.value:
                await _send_notice(callback, "Анкета ещё не заполнена. Нажмите «Заполнить анкету».")
                await _safe_callback_answer(callback)
                return
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id="S6",
        )
        await _safe_callback_answer(callback)
        if not await _notify_llm_unavailable(callback):
            await screen_manager.show_screen(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                user_id=callback.from_user.id,
                screen_id="S10",
            )
            await _safe_callback_answer(callback)
            return
        with get_session() as session:
            user = _get_or_create_user(session, callback.from_user.id)
            user_id = user.id
        report = await _generate_report_with_retry(
            callback,
            user_id=user_id,
            state=screen_manager.update_state(callback.from_user.id).data,
        )
        if report:
            screen_manager.update_state(
                callback.from_user.id,
                report_text=report.text,
                report_provider=report.provider,
                report_model=report.model,
            )
            await _run_report_delay(
                callback.bot,
                callback.message.chat.id,
                callback.from_user.id,
            )
            await _ensure_report_delivery(callback, "S7")
            with get_session() as session:
                latest_report = _get_latest_report(
                    session,
                    callback.from_user.id,
                    tariff_value=tariff,
                )
                report_meta = _get_report_pdf_meta(latest_report)
                latest_report_id = report_meta.get("id") if report_meta else None
                pdf_bytes = (
                    _get_report_pdf_bytes(session, latest_report)
                    if latest_report
                    else None
                )
            if latest_report_id and not await _send_report_pdf(
                callback.bot,
                callback.message.chat.id,
                report_meta,
                pdf_bytes=pdf_bytes,
                username=callback.from_user.username,
                user_id=callback.from_user.id,
            ):
                await _send_notice(
                    callback,
                    "Не удалось сформировать PDF автоматически. "
                    "Вы можете попробовать кнопку «Выгрузить PDF»."
                )
        else:
            await screen_manager.show_screen(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                user_id=callback.from_user.id,
                screen_id="S10",
            )
        await _safe_callback_answer(callback)
        return

    if callback.data.startswith("report:view:"):
        report_id = _safe_int(callback.data.split("report:view:")[-1])
        if not report_id:
            await _send_notice(callback, "Не удалось открыть отчёт. Попробуйте выбрать его ещё раз.")
            await _safe_callback_answer(callback)
            return
        with get_session() as session:
            report = _get_report_for_user(session, callback.from_user.id, report_id)
            if not report:
                await _send_notice(callback, "Отчёт не найден. Обновите список в кабинете.")
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

    if callback.data.startswith("report:delete:") and callback.data != "report:delete:confirm":
        report_id = _safe_int(callback.data.split("report:delete:")[-1])
        if not report_id:
            await _send_notice(callback, "Не удалось выбрать отчёт для удаления.")
            await _safe_callback_answer(callback)
            return
        with get_session() as session:
            report = _get_report_for_user(session, callback.from_user.id, report_id)
            if not report:
                await _send_notice(callback, "Отчёт не найден. Обновите список.")
                await _safe_callback_answer(callback)
                return
            screen_manager.update_state(
                callback.from_user.id,
                report_meta=_report_meta_payload(report),
                report_text=report.report_text,
            )
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id="S14",
        )
        await _safe_callback_answer(callback)
        return

    if callback.data == "report:delete:confirm":
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        report_meta = state_snapshot.data.get("report_meta") or {}
        report_id = _safe_int(report_meta.get("id"))
        if not report_id:
            await _send_notice(callback, "Не удалось удалить отчёт. Попробуйте ещё раз.")
            await _safe_callback_answer(callback)
            return
        with get_session() as session:
            report = _get_report_for_user(session, callback.from_user.id, report_id)
            if not report:
                await _send_notice(callback, "Отчёт уже удалён или недоступен.")
            else:
                pdf_service.delete_pdf(report.pdf_storage_key)
                session.delete(report)
            _refresh_reports_list_state(session, callback.from_user.id)
        screen_manager.update_state(
            callback.from_user.id,
            report_text=None,
            report_meta=None,
        )
        await _send_notice(callback, "Отчёт удалён.")
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id="S12",
        )
        await _safe_callback_answer(callback)
        return

    if callback.data.startswith("report:pdf:"):
        report_id = _safe_int(callback.data.split("report:pdf:")[-1])
        if not report_id:
            await _send_notice(callback, "Не удалось сформировать PDF. Попробуйте ещё раз.")
            await _safe_callback_answer(callback)
            return
        with get_session() as session:
            report = _get_report_for_user(session, callback.from_user.id, report_id)
            if not report:
                await _send_notice(callback, "Отчёт не найден. Попробуйте выбрать другой.")
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
                callback,
                "Не удалось сформировать PDF. Попробуйте ещё раз чуть позже."
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
                await _send_notice(callback, "PDF будет доступен после генерации отчёта.")
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
                callback,
                "Не удалось сформировать PDF. Попробуйте ещё раз чуть позже."
            )
        await _safe_callback_answer(callback)
        return

    if callback.data == "feedback:send":
        state_snapshot = screen_manager.update_state(callback.from_user.id)
        feedback_text = state_snapshot.data.get("feedback_text") or ""

        feedback_mode = (settings.feedback_mode or "native").lower()
        status = FeedbackStatus.SENT
        sent_at = datetime.now(timezone.utc)
        if feedback_mode != "native":
            status = FeedbackStatus.FAILED
            sent_at = None
            if settings.feedback_group_url:
                await _send_notice(callback, 
                    "Обратная связь настроена через livegram. "
                    "Нажмите «Перейти в группу», чтобы отправить сообщение."
                )
            else:
                await _send_notice(callback, 
                    "Обратная связь настроена через livegram, но ссылка на группу не указана."
                )
        elif not settings.feedback_group_chat_id:
            status = FeedbackStatus.FAILED
            sent_at = None
            await _send_notice(callback, 
                "Чат для обратной связи не настроен. "
                "Добавьте FEEDBACK_GROUP_CHAT_ID или используйте livegram."
            )
        else:
            try:
                await callback.bot.send_message(
                    chat_id=settings.feedback_group_chat_id,
                    text=f"Сообщение от пользователя {callback.from_user.id}:\n{feedback_text}",
                )
            except Exception as exc:
                status = FeedbackStatus.FAILED
                sent_at = None
                logger.warning(
                    "feedback_send_failed",
                    extra={"user_id": callback.from_user.id, "error": str(exc)},
                )

        try:
            with get_session() as session:
                user = _get_or_create_user(session, callback.from_user.id)
                session.add(
                    FeedbackMessage(
                        user_id=user.id,
                        text=feedback_text,
                        status=status,
                        sent_at=sent_at,
                    )
                )
        except Exception as exc:
            logger.warning(
                "feedback_store_failed",
                extra={"user_id": callback.from_user.id, "error": str(exc)},
            )

        if status == FeedbackStatus.SENT:
            await _send_notice(callback, "Сообщение отправлено. Спасибо за обратную связь!")
            screen_manager.update_state(callback.from_user.id, feedback_text=None)
        else:
            await _send_notice(callback, 
                "Не удалось отправить сообщение. Попробуйте позже или используйте «Перейти в группу»."
            )
        await _safe_callback_answer(callback)
        return

    await _safe_callback_answer(callback)
