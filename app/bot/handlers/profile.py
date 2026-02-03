from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import delete, select

from app.bot.handlers.screen_manager import screen_manager
from app.core.config import settings
from app.db.models import (
    FeedbackMessage,
    FreeLimit,
    Order,
    OrderStatus,
    QuestionnaireResponse,
    Report,
    User,
    UserProfile,
)
from app.db.session import get_session

router = Router()


class ProfileStates(StatesGroup):
    name = State()
    birth_date = State()
    birth_time = State()
    birth_place = State()


def _safe_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _profile_payload(profile: UserProfile | None) -> dict[str, Any]:
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


async def _show_profile_screen(message: Message, user_id: int) -> None:
    await screen_manager.show_screen(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=user_id,
        screen_id="S4",
    )


def _clear_user_data(session, user: User) -> None:
    session.execute(delete(UserProfile).where(UserProfile.user_id == user.id))
    session.execute(delete(Order).where(Order.user_id == user.id))
    session.execute(delete(FreeLimit).where(FreeLimit.user_id == user.id))
    session.execute(
        delete(FeedbackMessage).where(FeedbackMessage.user_id == user.id)
    )
    session.execute(
        delete(QuestionnaireResponse).where(QuestionnaireResponse.user_id == user.id)
    )
    session.execute(delete(Report).where(Report.user_id == user.id))


async def start_profile_wizard(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ProfileStates.name)
    await message.answer("Введите имя (в любом формате).")


async def _ensure_paid_profile_access(callback: CallbackQuery) -> bool:
    state_snapshot = screen_manager.update_state(callback.from_user.id)
    selected_tariff = state_snapshot.data.get("selected_tariff")
    if not selected_tariff:
        await callback.message.answer("Сначала выберите тариф.")
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id="S1",
        )
        return False
    if selected_tariff == "T0":
        with get_session() as session:
            t0_allowed, next_available = _t0_cooldown_status(
                session, callback.from_user.id
            )
        if not t0_allowed:
            screen_manager.update_state(
                callback.from_user.id,
                selected_tariff="T0",
                t0_next_available=next_available,
            )
            await screen_manager.show_screen(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                user_id=callback.from_user.id,
                screen_id="S9",
            )
            return False
    if selected_tariff not in {"T1", "T2", "T3"}:
        return True

    order_id = state_snapshot.data.get("order_id")
    order_id = _safe_int(order_id)
    if not order_id:
        await callback.message.answer("Сначала выберите тариф и завершите оплату.")
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id="S1",
        )
        return False

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order or order.status != OrderStatus.PAID:
            if order:
                screen_manager.update_state(
                    callback.from_user.id,
                    order_id=str(order.id),
                    order_status=order.status.value,
                    order_amount=str(order.amount),
                    order_currency=order.currency,
                )
            await callback.message.answer(
                "Оплата ещё не подтверждена. Доступ к вводу данных откроется после статуса paid."
            )
            await screen_manager.show_screen(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                user_id=callback.from_user.id,
                screen_id="S3",
            )
            return False
    return True


@router.callback_query(F.data == "profile:start")
async def start_profile_flow(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_paid_profile_access(callback):
        await callback.answer()
        return
    await start_profile_wizard(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "profile:delete:confirm")
async def delete_profile_data(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    with get_session() as session:
        user = _get_or_create_user(session, callback.from_user.id)
        _clear_user_data(session, user)
    screen_manager.clear_state(callback.from_user.id)
    await callback.message.answer(
        "Ваши данные удалены. Вы можете заполнить их заново в любой момент."
    )
    await _show_profile_screen(callback.message, callback.from_user.id)
    await callback.answer()


@router.message(Command("cancel"))
@router.message(F.text.casefold() == "отмена")
async def cancel_profile(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        return
    await state.clear()
    await message.answer("Ввод данных отменён.")
    await _show_profile_screen(message, message.from_user.id)


@router.message(ProfileStates.name)
async def handle_profile_name(message: Message, state: FSMContext) -> None:
    name = message.text or ""
    await state.update_data(name=name)
    await state.set_state(ProfileStates.birth_date)
    await message.answer("Введите дату рождения (в любом формате).")


@router.message(ProfileStates.birth_date)
async def handle_profile_birth_date(message: Message, state: FSMContext) -> None:
    birth_date = message.text or ""
    await state.update_data(birth_date=birth_date)
    await state.set_state(ProfileStates.birth_time)
    await message.answer("Введите время рождения (в любом формате).")


@router.message(ProfileStates.birth_time)
async def handle_profile_birth_time(message: Message, state: FSMContext) -> None:
    birth_time = message.text or ""
    await state.update_data(birth_time=birth_time)
    await state.set_state(ProfileStates.birth_place)
    await message.answer("Введите место рождения (в любом формате).")


@router.message(ProfileStates.birth_place)
async def handle_profile_birth_place(message: Message, state: FSMContext) -> None:
    birth_place = message.text or ""
    data = await state.get_data()
    with get_session() as session:
        user = _get_or_create_user(session, message.from_user.id)
        profile = user.profile
        if profile:
            profile.name = data["name"]
            profile.birth_date = data["birth_date"]
            profile.birth_time = data["birth_time"]
            profile.birth_place_city = birth_place
            profile.birth_place_region = None
            profile.birth_place_country = ""
        else:
            profile = UserProfile(
                user_id=user.id,
                name=data["name"],
                birth_date=data["birth_date"],
                birth_time=data["birth_time"],
                birth_place_city=birth_place,
                birth_place_region=None,
                birth_place_country="",
            )
            session.add(profile)
        session.flush()
        screen_manager.update_state(
            message.from_user.id,
            **_profile_payload(profile),
        )
    await state.clear()
    await message.answer("Данные сохранены.")
    await _show_profile_screen(message, message.from_user.id)
