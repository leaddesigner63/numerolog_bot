from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.bot.screen_manager import screen_manager
from app.core.config import settings
from app.db.models import FreeLimit, Order, OrderStatus, PaymentProvider, Tariff, User
from app.db.session import get_session


router = Router()

TARIFF_PRICES = {
    Tariff.T1: 560,
    Tariff.T2: 2190,
    Tariff.T3: 5930,
}


def _get_payment_provider() -> PaymentProvider:
    provider = settings.payment_provider.lower()
    if provider == PaymentProvider.CLOUDPAYMENTS.value:
        return PaymentProvider.CLOUDPAYMENTS
    if provider == PaymentProvider.PRODAMUS.value:
        return PaymentProvider.PRODAMUS
    return PaymentProvider.PRODAMUS


def _get_or_create_user(session, telegram_user_id: int) -> User:
    user = session.execute(
        select(User).where(User.telegram_user_id == telegram_user_id)
    ).scalar_one_or_none()
    if user:
        if not user.free_limit:
            session.add(FreeLimit(user_id=user.id))
        return user

    user = User(telegram_user_id=telegram_user_id)
    session.add(user)
    session.flush()
    session.add(FreeLimit(user_id=user.id))
    return user


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
                if last_t0_at and datetime.utcnow() < last_t0_at + cooldown:
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
        else:
            with get_session() as session:
                user = _get_or_create_user(session, callback.from_user.id)
                order = _create_order(session, user, Tariff(tariff))
                screen_manager.update_state(
                    callback.from_user.id,
                    selected_tariff=tariff,
                    **_refresh_order_state(order),
                )

        screen_manager.update_state(callback.from_user.id, selected_tariff=tariff)
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
            if not order or order.status != OrderStatus.PAID:
                if order:
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
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id="S4",
        )
        await callback.answer()
        return

    if callback.data == "profile:save":
        state = screen_manager.update_state(callback.from_user.id)
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
                    user.free_limit.last_t0_at = datetime.utcnow()
        next_screen = "S5" if tariff in {Tariff.T2.value, Tariff.T3.value} else "S6"
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
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id="S6",
        )
        await callback.answer()
        return

    if callback.data == "report:pdf":
        await callback.message.answer("PDF будет доступен после генерации отчёта.")
        await callback.answer()
        return

    if callback.data == "feedback:send":
        await callback.message.answer("Сообщение будет отправлено в группу после запуска потока обратной связи.")
        await callback.answer()
        return

    await callback.answer()
