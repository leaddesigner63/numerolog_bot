from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from aiogram import Router
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy import select

from app.bot.questionnaire.config import load_questionnaire_config
from app.bot.handlers.screen_manager import screen_manager
from app.core.config import settings
from app.core.pdf_service import pdf_service
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


def _get_payment_provider() -> PaymentProviderEnum:
    provider = settings.payment_provider.lower()
    if provider == PaymentProviderEnum.CLOUDPAYMENTS.value:
        return PaymentProviderEnum.CLOUDPAYMENTS
    if provider == PaymentProviderEnum.PRODAMUS.value:
        return PaymentProviderEnum.PRODAMUS
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
            "birth_date": profile.birth_date.isoformat(),
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
    report = session.execute(query.order_by(Report.created_at.desc())).scalar_one_or_none()
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
    return session.execute(query.order_by(Report.created_at.desc())).scalar_one_or_none()


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
async def handle_callbacks(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer()
        return

    if callback.data.startswith("screen:"):
        screen_id = callback.data.split("screen:")[-1]
        if screen_id == "S4":
            with get_session() as session:
                _refresh_profile_state(session, callback.from_user.id)
        if screen_id == "S5":
            with get_session() as session:
                _refresh_questionnaire_state(session, callback.from_user.id)
        if screen_id == "S7":
            state = screen_manager.update_state(callback.from_user.id)
            with get_session() as session:
                _refresh_report_state(
                    session,
                    callback.from_user.id,
                    tariff_value=state.data.get("selected_tariff"),
                )
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id=screen_id,
        )
        await callback.answer()
        return

    if callback.data.startswith("tariff:"):
        tariff = callback.data.split("tariff:")[-1]
        if tariff == Tariff.T0.value:
            with get_session() as session:
                user = _get_or_create_user(session, callback.from_user.id)
                free_limit = user.free_limit
                last_t0_at = free_limit.last_t0_at if free_limit else None
                cooldown = timedelta(hours=settings.free_t0_cooldown_hours)
                now = datetime.now(timezone.utc)
                if last_t0_at and now < last_t0_at + cooldown:
                    next_available = last_t0_at + cooldown
                    screen_manager.update_state(
                        callback.from_user.id,
                        selected_tariff=tariff,
                        t0_next_available=next_available.strftime("%Y-%m-%d %H:%M UTC"),
                    )
                    await screen_manager.show_screen(
                        bot=callback.bot,
                        chat_id=callback.message.chat.id,
                        user_id=callback.from_user.id,
                        screen_id="S9",
                    )
                    await callback.answer()
                    return
                _refresh_profile_state(session, callback.from_user.id)
        else:
            with get_session() as session:
                user = _get_or_create_user(session, callback.from_user.id)
                order = _create_order(session, user, Tariff(tariff))
                provider = get_payment_provider(order.provider.value)
                payment_link = provider.create_payment_link(order, user=user)
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
        )
        next_screen = "S4" if tariff == Tariff.T0.value else "S2"
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id=next_screen,
        )
        await callback.answer()
        return

    if callback.data == "payment:paid":
        state = screen_manager.update_state(callback.from_user.id)
        order_id = state.data.get("order_id")
        if not order_id:
            await callback.message.answer("Сначала выберите тариф и создайте заказ.")
            await callback.answer()
            return
        with get_session() as session:
            order = session.get(Order, int(order_id))
            if not order:
                await callback.message.answer("Заказ не найден. Попробуйте выбрать тариф заново.")
                await callback.answer()
                return
            if order.status != OrderStatus.PAID:
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
                    await callback.message.answer(
                        "Оплата ещё не подтверждена. Мы проверим статус и сообщим, когда всё будет готово."
                    )
                    await screen_manager.show_screen(
                        bot=callback.bot,
                        chat_id=callback.message.chat.id,
                        user_id=callback.from_user.id,
                        screen_id="S3",
                    )
                    await callback.answer()
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
        await callback.answer()
        return

    if callback.data == "profile:save":
        _ensure_profile_state(callback.from_user.id)
        state = screen_manager.update_state(callback.from_user.id)
        if not state.data.get("profile"):
            await callback.message.answer("Сначала заполните «Мои данные».")
            await callback.answer()
            return
        tariff = state.data.get("selected_tariff")
        if tariff in {Tariff.T1.value, Tariff.T2.value, Tariff.T3.value}:
            order_id = state.data.get("order_id")
            if not order_id:
                await callback.message.answer("Сначала выберите тариф и завершите оплату.")
                await callback.answer()
                return
            with get_session() as session:
                order = session.get(Order, int(order_id))
                if not order or order.status != OrderStatus.PAID:
                    if order:
                        screen_manager.update_state(
                            callback.from_user.id, **_refresh_order_state(order)
                        )
                    await callback.message.answer(
                        "Оплата ещё не подтверждена. Доступ к генерации откроется после статуса paid."
                    )
                    await screen_manager.show_screen(
                        bot=callback.bot,
                        chat_id=callback.message.chat.id,
                        user_id=callback.from_user.id,
                        screen_id="S3",
                    )
                    await callback.answer()
                    return
        if tariff == Tariff.T0.value:
            with get_session() as session:
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
            report = await report_service.generate_report(
                user_id=callback.from_user.id,
                state=screen_manager.update_state(callback.from_user.id).data,
            )
            if report:
                screen_manager.update_state(
                    callback.from_user.id,
                    report_text=report.text,
                    report_provider=report.provider,
                    report_model=report.model,
                )
                await screen_manager.show_screen(
                    bot=callback.bot,
                    chat_id=callback.message.chat.id,
                    user_id=callback.from_user.id,
                    screen_id="S7",
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
        await callback.answer()
        return

    if callback.data == "questionnaire:done":
        state = screen_manager.update_state(callback.from_user.id)
        tariff = state.data.get("selected_tariff")
        if tariff in {Tariff.T2.value, Tariff.T3.value}:
            order_id = state.data.get("order_id")
            if not order_id:
                await callback.message.answer("Сначала выберите тариф и завершите оплату.")
                await callback.answer()
                return
            with get_session() as session:
                order = session.get(Order, int(order_id))
                if not order or order.status != OrderStatus.PAID:
                    if order:
                        screen_manager.update_state(
                            callback.from_user.id, **_refresh_order_state(order)
                        )
                    await callback.message.answer(
                        "Оплата ещё не подтверждена. Генерация будет доступна после статуса paid."
                    )
                    await screen_manager.show_screen(
                        bot=callback.bot,
                        chat_id=callback.message.chat.id,
                        user_id=callback.from_user.id,
                        screen_id="S3",
                    )
                    await callback.answer()
                    return
            questionnaire = state.data.get("questionnaire") or {}
            if questionnaire.get("status") != QuestionnaireStatus.COMPLETED.value:
                await callback.message.answer("Анкета ещё не заполнена. Нажмите «Заполнить анкету».")
                await callback.answer()
                return
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id="S6",
        )
        report = await report_service.generate_report(
            user_id=callback.from_user.id,
            state=screen_manager.update_state(callback.from_user.id).data,
        )
        if report:
            screen_manager.update_state(
                callback.from_user.id,
                report_text=report.text,
                report_provider=report.provider,
                report_model=report.model,
            )
            await screen_manager.show_screen(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                user_id=callback.from_user.id,
                screen_id="S7",
            )
        else:
            await screen_manager.show_screen(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                user_id=callback.from_user.id,
                screen_id="S10",
            )
        await callback.answer()
        return

    if callback.data == "report:pdf":
        state = screen_manager.update_state(callback.from_user.id)
        with get_session() as session:
            report = _get_latest_report(
                session,
                callback.from_user.id,
                tariff_value=state.data.get("selected_tariff"),
            )
            if not report:
                await callback.message.answer("PDF будет доступен после генерации отчёта.")
                await callback.answer()
                return
            if report.pdf_storage_key:
                pdf_bytes = pdf_service.load_pdf(report.pdf_storage_key)
            else:
                pdf_bytes = pdf_service.generate_pdf(report.report_text)
                report.pdf_storage_key = pdf_service.store_pdf(report.id, pdf_bytes)
                session.add(report)
        filename = f"report_{report.id}.pdf"
        await callback.message.answer_document(
            BufferedInputFile(pdf_bytes, filename=filename)
        )
        await callback.answer()
        return

    if callback.data == "feedback:send":
        state = screen_manager.update_state(callback.from_user.id)
        feedback_text = (state.data.get("feedback_text") or "").strip()
        if not feedback_text:
            await callback.message.answer("Сначала напишите сообщение для обратной связи.")
            await callback.answer()
            return

        feedback_mode = (settings.feedback_mode or "native").lower()
        if feedback_mode != "native":
            if settings.feedback_group_url:
                await callback.message.answer(
                    "Обратная связь настроена через livegram. "
                    "Нажмите «Перейти в группу», чтобы отправить сообщение."
                )
            else:
                await callback.message.answer(
                    "Обратная связь настроена через livegram, но ссылка на группу не указана."
                )
            await callback.answer()
            return

        if not settings.feedback_group_chat_id:
            await callback.message.answer(
                "Чат для обратной связи не настроен. "
                "Добавьте FEEDBACK_GROUP_CHAT_ID или используйте livegram."
            )
            await callback.answer()
            return

        status = FeedbackStatus.SENT
        sent_at = datetime.now(timezone.utc)
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
            await callback.message.answer("Сообщение отправлено. Спасибо за обратную связь!")
            screen_manager.update_state(callback.from_user.id, feedback_text=None)
        else:
            await callback.message.answer(
                "Не удалось отправить сообщение. Попробуйте позже или используйте «Перейти в группу»."
            )
        await callback.answer()
        return

    await callback.answer()
