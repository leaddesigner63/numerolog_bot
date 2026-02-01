from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.bot.handlers.screen_manager import screen_manager
from app.db.models import User, UserProfile
from app.db.session import get_session

router = Router()

TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3])$")


class ProfileStates(StatesGroup):
    name = State()
    birth_date = State()
    birth_time = State()
    birth_place = State()


def _get_or_create_user(session, telegram_user_id: int) -> User:
    user = session.execute(
        select(User).where(User.telegram_user_id == telegram_user_id)
    ).scalar_one_or_none()
    if user:
        return user

    user = User(telegram_user_id=telegram_user_id)
    session.add(user)
    session.flush()
    return user


def _profile_payload(profile: UserProfile | None) -> dict[str, Any]:
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


def _parse_birth_date(value: str) -> datetime.date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_birth_time(value: str) -> str | None:
    normalized = value.strip()
    if TIME_PATTERN.match(normalized):
        return normalized
    return None


def _parse_birth_place(value: str) -> tuple[str, str | None, str] | None:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) < 2:
        return None
    city = parts[0]
    if len(parts) == 2:
        region = None
        country = parts[1]
    else:
        region = parts[1]
        country = ", ".join(parts[2:])
    if not city or not country:
        return None
    return city, region, country


async def _show_profile_screen(message: Message, user_id: int) -> None:
    await screen_manager.show_screen(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=user_id,
        screen_id="S4",
    )


@router.callback_query(F.data == "profile:start")
async def start_profile_flow(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ProfileStates.name)
    await callback.message.answer("Введите имя (как к вам обращаться).")
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
    name = (message.text or "").strip()
    if not name:
        await message.answer("Имя не может быть пустым. Введите имя ещё раз.")
        return
    await state.update_data(name=name)
    await state.set_state(ProfileStates.birth_date)
    await message.answer("Введите дату рождения в формате YYYY-MM-DD.")


@router.message(ProfileStates.birth_date)
async def handle_profile_birth_date(message: Message, state: FSMContext) -> None:
    birth_date = _parse_birth_date(message.text or "")
    if not birth_date:
        await message.answer("Неверный формат даты. Используйте YYYY-MM-DD.")
        return
    await state.update_data(birth_date=birth_date)
    await state.set_state(ProfileStates.birth_time)
    await message.answer("Введите час рождения в формате HH (00-23).")


@router.message(ProfileStates.birth_time)
async def handle_profile_birth_time(message: Message, state: FSMContext) -> None:
    birth_time = _parse_birth_time(message.text or "")
    if not birth_time:
        await message.answer("Неверный формат времени. Используйте HH (00-23).")
        return
    await state.update_data(birth_time=birth_time)
    await state.set_state(ProfileStates.birth_place)
    await message.answer("Введите место рождения: город, регион, страна.")


@router.message(ProfileStates.birth_place)
async def handle_profile_birth_place(message: Message, state: FSMContext) -> None:
    parsed_place = _parse_birth_place(message.text or "")
    if not parsed_place:
        await message.answer("Неверный формат. Используйте «город, регион, страна».")
        return
    city, region, country = parsed_place
    data = await state.get_data()
    with get_session() as session:
        user = _get_or_create_user(session, message.from_user.id)
        profile = user.profile
        if profile:
            profile.name = data["name"]
            profile.birth_date = data["birth_date"]
            profile.birth_time = data["birth_time"]
            profile.birth_place_city = city
            profile.birth_place_region = region
            profile.birth_place_country = country
        else:
            profile = UserProfile(
                user_id=user.id,
                name=data["name"],
                birth_date=data["birth_date"],
                birth_time=data["birth_time"],
                birth_place_city=city,
                birth_place_region=region,
                birth_place_country=country,
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
