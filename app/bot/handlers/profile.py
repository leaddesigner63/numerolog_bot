from __future__ import annotations

from datetime import timedelta
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.types import ReplyKeyboardRemove
from sqlalchemy import delete, select, func

from app.bot.questionnaire.config import load_questionnaire_config
from app.bot.handlers.screen_manager import screen_manager
from app.core.config import settings
from app.core.timezone import APP_TIMEZONE, format_app_datetime, now_app_timezone
from app.db.models import (
    FeedbackMessage,
    FreeLimit,
    MarketingConsentEvent,
    MarketingConsentEventType,
    Order,
    OrderStatus,
    QuestionnaireResponse,
    Report,
    ReportJob,
    ReportJobStatus,
    Tariff,
    User,
    UserProfile,
)
from app.db.session import get_session

router = Router()

GENDER_CALLBACK_TO_VALUE = {
    "profile:gender:female": "Женский",
    "profile:gender:male": "Мужской",
}

DATE_INPUT_HINT = "ДД.ММ.ГГГГ"
TIME_INPUT_HINT = "ЧЧ.ММ"


class ProfileStates(StatesGroup):
    name = State()
    gender = State()
    birth_date = State()
    birth_time = State()
    birth_place = State()
    edit_name = State()
    edit_gender = State()
    edit_birth_date = State()
    edit_birth_time = State()
    edit_birth_place = State()


def _gender_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Женский", callback_data="profile:gender:female"
                ),
                InlineKeyboardButton(text="Мужской", callback_data="profile:gender:male"),
            ]
        ]
    )


def _safe_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_state_data(state_snapshot: Any | None) -> dict[str, Any]:
    state_data = getattr(state_snapshot, "data", None)
    if isinstance(state_data, dict):
        return state_data
    return {}


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


def _profile_payload(profile: UserProfile | None) -> dict[str, Any]:
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


def _append_marketing_consent_event(
    *,
    session,
    user_id: int,
    event_type: MarketingConsentEventType,
    event_at,
    document_version: str | None,
    source: str | None,
    metadata_json: dict[str, Any] | None,
) -> None:
    session.add(
        MarketingConsentEvent(
            user_id=user_id,
            event_type=event_type,
            event_at=event_at,
            document_version=document_version,
            source=source,
            metadata_json=metadata_json,
        )
    )


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


def _refresh_reports_summary(session, telegram_user_id: int) -> None:
    user = session.execute(
        select(User).where(User.telegram_user_id == telegram_user_id)
    ).scalar_one_or_none()
    if not user:
        screen_manager.update_state(telegram_user_id, reports_total=0, reports=[])
        return
    total = session.execute(
        select(func.count(Report.id)).where(Report.user_id == user.id)
    ).scalar() or 0
    screen_manager.update_state(telegram_user_id, reports_total=total)


def _refresh_questionnaire_summary(session, telegram_user_id: int) -> None:
    config = load_questionnaire_config()
    user = _get_or_create_user(session, telegram_user_id)
    response = session.execute(
        select(QuestionnaireResponse).where(
            QuestionnaireResponse.user_id == user.id,
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


def _create_report_job_for_consent(
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

    if tariff in {Tariff.T1, Tariff.T2, Tariff.T3}:
        if order_id is None:
            return None
        order = session.get(Order, order_id)
        if not order or order.user_id != user.id or order.tariff != tariff:
            return None
        if order.status != OrderStatus.PAID:
            return None
    else:
        order_id = None

    existing_job = (
        session.execute(
            select(ReportJob)
            .where(
                ReportJob.user_id == user.id,
                ReportJob.tariff == tariff,
                ReportJob.status.in_([ReportJobStatus.PENDING, ReportJobStatus.IN_PROGRESS]),
                ReportJob.order_id.is_(None) if order_id is None else ReportJob.order_id == order_id,
            )
            .order_by(ReportJob.created_at.desc())
            .limit(1)
        )
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


@router.message(Command("lk"))
async def show_cabinet(message: Message) -> None:
    if not message.from_user:
        return
    with get_session() as session:
        user = _get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
        )
        screen_manager.update_state(message.from_user.id, **_profile_payload(user.profile))
        _refresh_reports_summary(session, message.from_user.id)
        _refresh_questionnaire_summary(session, message.from_user.id)
    screen_manager.add_user_message_id(message.from_user.id, message.message_id)
    await screen_manager.show_screen(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        screen_id="S11",
    )
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )


async def start_profile_wizard(
    message: Message, state: FSMContext, user_id: int
) -> None:
    await state.clear()
    await state.set_state(ProfileStates.name)
    await screen_manager.enter_text_input_mode(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=user_id,
    )
    sent = await message.bot.send_message(
        chat_id=message.chat.id,
        text="Введите свое имя",
    )
    screen_manager.update_last_question_message_id(user_id, sent.message_id)


async def _start_profile_edit(
    callback: CallbackQuery,
    state: FSMContext,
    next_state: State,
    prompt: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardRemove | None = None,
) -> None:
    await state.clear()
    await state.set_state(next_state)
    await screen_manager.delete_last_question_message(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
    )
    if reply_markup is None:
        await screen_manager.enter_text_input_mode(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            preserve_last_question=True,
        )
    sent = await callback.bot.send_message(
        chat_id=callback.message.chat.id,
        text=prompt,
        reply_markup=reply_markup,
    )
    screen_manager.update_last_question_message_id(
        callback.from_user.id, sent.message_id
    )


async def _ensure_profile_access(callback: CallbackQuery) -> bool:
    state_snapshot = screen_manager.update_state(callback.from_user.id)
    selected_tariff = state_snapshot.data.get("selected_tariff")
    if not selected_tariff:
        await screen_manager.send_ephemeral_message(
            callback.message, "Сначала выберите тариф.", user_id=callback.from_user.id
        )
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

    return True


@router.callback_query(F.data == "profile:start")
async def start_profile_flow(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_profile_access(callback):
        await callback.answer()
        return
    await start_profile_wizard(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "profile:consent:accept")
async def accept_profile_consent(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return

    consent_saved = False
    report_job_ready = True
    with get_session() as session:
        user = _get_or_create_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
        )
        profile = user.profile
        if profile:
            consent_at = now_app_timezone()
            profile.personal_data_consent_accepted_at = consent_at
            profile.personal_data_consent_source = "profile_flow"
            session.flush()
            screen_manager.update_state(
                callback.from_user.id,
                **_profile_payload(profile),
            )
            consent_saved = True

        if profile:
            state_snapshot = screen_manager.update_state(callback.from_user.id)
            state_data = _safe_state_data(state_snapshot)
            tariff = state_data.get("selected_tariff")
            if tariff not in {Tariff.T2.value, Tariff.T3.value}:
                order_id = _safe_int(state_data.get("order_id"))
                job = _create_report_job_for_consent(
                    session,
                    user=user,
                    tariff_value=tariff,
                    order_id=order_id,
                    chat_id=callback.message.chat.id,
                )
                report_job_ready = job is not None

    if not consent_saved:
        await screen_manager.send_ephemeral_message(
            callback.message,
            "Сначала заполните «Мои данные».",
            user_id=callback.from_user.id,
        )
        await _show_profile_screen(callback.message, callback.from_user.id)
        await callback.answer()
        return

    state_snapshot = screen_manager.update_state(
        callback.from_user.id,
        profile_flow=None,
    )
    state_data = _safe_state_data(state_snapshot)
    tariff = state_data.get("selected_tariff")
    next_screen = "S5" if tariff in {"T2", "T3"} else "S6"

    if next_screen == "S6" and not report_job_ready:
        await screen_manager.send_ephemeral_message(
            callback.message,
            "Не удалось запустить генерацию отчёта. Попробуйте снова.",
            user_id=callback.from_user.id,
        )
        await callback.answer()
        return

    await screen_manager.send_ephemeral_message(
        callback.message,
        "Согласие подтверждено.",
        user_id=callback.from_user.id,
    )
    await screen_manager.show_screen(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        screen_id=next_screen,
    )
    await callback.answer()


@router.callback_query(F.data == "profile:marketing_consent:accept")
async def accept_marketing_consent(callback: CallbackQuery) -> None:
    if not callback.from_user:
        await callback.answer()
        return

    with get_session() as session:
        user = _get_or_create_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
        )
        profile = user.profile
        if profile:
            accepted_at = now_app_timezone()
            profile.marketing_consent_accepted_at = accepted_at
            profile.marketing_consent_revoked_at = None
            profile.marketing_consent_document_version = "v1"
            profile.marketing_consent_source = "profile_flow"
            profile.marketing_consent_revoked_source = None
            _append_marketing_consent_event(
                session=session,
                user_id=user.id,
                event_type=MarketingConsentEventType.ACCEPTED,
                event_at=accepted_at,
                document_version=profile.marketing_consent_document_version,
                source=profile.marketing_consent_source,
                metadata_json={"handler": "profile:marketing_consent:accept"},
            )

    await callback.answer()


@router.callback_query(F.data == "profile:marketing_consent:revoke")
async def revoke_marketing_consent(callback: CallbackQuery) -> None:
    if not callback.from_user:
        await callback.answer()
        return

    with get_session() as session:
        user = _get_or_create_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
        )
        profile = user.profile
        if profile:
            revoked_at = now_app_timezone()
            profile.marketing_consent_revoked_at = revoked_at
            profile.marketing_consent_revoked_source = "profile_flow"
            _append_marketing_consent_event(
                session=session,
                user_id=user.id,
                event_type=MarketingConsentEventType.REVOKED,
                event_at=revoked_at,
                document_version=profile.marketing_consent_document_version,
                source=profile.marketing_consent_revoked_source,
                metadata_json={"handler": "profile:marketing_consent:revoke"},
            )

    await callback.answer()




@router.callback_query(F.data == "marketing:consent:accept")
async def accept_marketing_consent_prompt(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return

    now = now_app_timezone()
    with get_session() as session:
        user = _get_or_create_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
        )
        profile = user.profile
        if profile:
            profile.marketing_consent_accepted_at = now
            profile.marketing_consent_revoked_at = None
            profile.marketing_consent_document_version = "v1"
            profile.marketing_consent_source = "marketing_prompt"
            profile.marketing_consent_revoked_source = None
            _append_marketing_consent_event(
                session=session,
                user_id=user.id,
                event_type=MarketingConsentEventType.ACCEPTED,
                event_at=now,
                document_version=profile.marketing_consent_document_version,
                source=profile.marketing_consent_source,
                metadata_json={"handler": "marketing:consent:accept"},
            )

    state_snapshot = screen_manager.update_state(callback.from_user.id)
    return_screen_id = state_snapshot.data.get("marketing_consent_return_screen") or "S11"
    screen_manager.update_state(
        callback.from_user.id,
        marketing_consent_choice="accept",
        marketing_consent_last_prompted_at=now.isoformat(),
        marketing_consent_last_action_at=now.isoformat(),
        marketing_consent_return_screen=None,
    )
    await screen_manager.send_ephemeral_message(
        callback.message,
        "Отлично! Подписку на полезную рассылку включили.",
        user_id=callback.from_user.id,
    )
    await screen_manager.show_screen(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        screen_id=return_screen_id,
    )
    await callback.answer()


@router.callback_query(F.data == "marketing:consent:skip")
async def skip_marketing_consent_prompt(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return

    now = now_app_timezone()
    state_snapshot = screen_manager.update_state(callback.from_user.id)
    return_screen_id = state_snapshot.data.get("marketing_consent_return_screen") or "S11"
    screen_manager.update_state(
        callback.from_user.id,
        marketing_consent_choice="skip",
        marketing_consent_last_prompted_at=now.isoformat(),
        marketing_consent_last_action_at=now.isoformat(),
        marketing_consent_return_screen=None,
    )
    await screen_manager.send_ephemeral_message(
        callback.message,
        "Хорошо, вернёмся к этому позже.",
        user_id=callback.from_user.id,
    )
    await screen_manager.show_screen(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        screen_id=return_screen_id,
    )
    await callback.answer()

@router.callback_query(F.data == "profile:edit:name")
async def start_profile_edit_name(callback: CallbackQuery, state: FSMContext) -> None:
    await _start_profile_edit(
        callback,
        state,
        ProfileStates.edit_name,
        "Введите новое имя (в любом формате).",
    )
    await callback.answer()


@router.callback_query(F.data == "profile:edit:birth_date")
async def start_profile_edit_birth_date(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await _start_profile_edit(
        callback,
        state,
        ProfileStates.edit_birth_date,
        f"Введите новую дату рождения ({DATE_INPUT_HINT}).",
    )
    await callback.answer()


@router.callback_query(F.data == "profile:edit:gender")
async def start_profile_edit_gender(callback: CallbackQuery, state: FSMContext) -> None:
    await _start_profile_edit(
        callback,
        state,
        ProfileStates.edit_gender,
        "Выберите пол.",
        reply_markup=_gender_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "profile:edit:birth_time")
async def start_profile_edit_birth_time(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await _start_profile_edit(
        callback,
        state,
        ProfileStates.edit_birth_time,
        f"Введите новое время рождения ({TIME_INPUT_HINT}).",
    )
    await callback.answer()


@router.callback_query(F.data == "profile:edit:birth_place")
async def start_profile_edit_birth_place(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await _start_profile_edit(
        callback,
        state,
        ProfileStates.edit_birth_place,
        "Введите новое место рождения (в любом формате).",
    )
    await callback.answer()


@router.callback_query(F.data == "profile:delete:confirm")
async def delete_profile_data(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    with get_session() as session:
        user = _get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        _clear_user_data(session, user)
        _refresh_reports_summary(session, callback.from_user.id)
        _refresh_questionnaire_summary(session, callback.from_user.id)
    screen_manager.update_state(
        callback.from_user.id,
        profile=None,
        reports=[],
        selected_tariff=None,
        order_id=None,
        order_status=None,
        order_amount=None,
        order_currency=None,
        profile_flow=None,
        t0_next_available=None,
    )
    await screen_manager.send_ephemeral_message(
        callback.message,
        "Анкетные данные удалены. Отчёты сохранены в «Мои отчёты».",
        user_id=callback.from_user.id,
    )
    await _show_profile_screen(callback.message, callback.from_user.id)
    await callback.answer()


@router.message(Command("cancel"))
@router.message(F.text.casefold() == "отмена")
async def cancel_profile(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    if await state.get_state() is None:
        await screen_manager.delete_user_message(
            bot=message.bot,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            message_id=message.message_id,
        )
        return
    screen_manager.add_user_message_id(message.from_user.id, message.message_id)
    await screen_manager.delete_last_question_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    await state.clear()
    await screen_manager.send_ephemeral_message(message, "Ввод данных отменён.")
    await _show_profile_screen(message, message.from_user.id)
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )


@router.message(ProfileStates.name)
async def handle_profile_name(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    screen_manager.add_user_message_id(message.from_user.id, message.message_id)
    await screen_manager.delete_last_question_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    name = message.text or ""
    await state.update_data(name=name)
    await state.set_state(ProfileStates.gender)
    sent = await message.bot.send_message(
        chat_id=message.chat.id,
        text="Выберите пол.",
        reply_markup=_gender_keyboard(),
    )
    screen_manager.update_last_question_message_id(message.from_user.id, sent.message_id)
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )


@router.message(ProfileStates.gender)
async def handle_profile_gender(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    screen_manager.add_user_message_id(message.from_user.id, message.message_id)
    await screen_manager.delete_last_question_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    gender = message.text or ""
    await state.update_data(gender=gender)
    await state.set_state(ProfileStates.birth_date)
    sent = await message.bot.send_message(
        chat_id=message.chat.id,
        text=f"Введите дату рождения ({DATE_INPUT_HINT}).",
    )
    screen_manager.update_last_question_message_id(message.from_user.id, sent.message_id)
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )


@router.callback_query(F.data.in_(set(GENDER_CALLBACK_TO_VALUE)))
async def handle_profile_gender_callback(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.message:
        await callback.answer()
        return
    current_state = await state.get_state()
    if current_state not in {ProfileStates.gender.state, ProfileStates.edit_gender.state}:
        await callback.answer()
        return
    await screen_manager.delete_last_question_message(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
    )
    await screen_manager.enter_text_input_mode(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        preserve_last_question=True,
    )
    gender = GENDER_CALLBACK_TO_VALUE.get(callback.data or "", "")
    if current_state == ProfileStates.gender.state:
        await state.update_data(gender=gender)
        await state.set_state(ProfileStates.birth_date)
        sent = await callback.bot.send_message(
            chat_id=callback.message.chat.id,
            text=f"Введите дату рождения ({DATE_INPUT_HINT}).",
        )
        screen_manager.update_last_question_message_id(
            callback.from_user.id, sent.message_id
        )
        await callback.answer("Пол сохранён")
        return

    with get_session() as session:
        user = _get_or_create_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
        )
        profile = user.profile
        if not profile:
            await state.clear()
            await screen_manager.send_ephemeral_message(
                callback.message, "Сначала заполните «Мои данные»."
            )
            await _show_profile_screen(callback.message, callback.from_user.id)
            await callback.answer()
            return
        profile.gender = gender
        session.flush()
        screen_manager.update_state(
            callback.from_user.id,
            **_profile_payload(profile),
        )
    await state.clear()
    await screen_manager.send_ephemeral_message(callback.message, "Данные обновлены.")
    await _show_profile_screen(callback.message, callback.from_user.id)
    await callback.answer("Пол обновлён")


@router.message(ProfileStates.birth_date)
async def handle_profile_birth_date(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    screen_manager.add_user_message_id(message.from_user.id, message.message_id)
    await screen_manager.delete_last_question_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    birth_date = message.text or ""
    await state.update_data(birth_date=birth_date)
    await state.set_state(ProfileStates.birth_time)
    sent = await message.bot.send_message(
        chat_id=message.chat.id,
        text=f"Введите время рождения ({TIME_INPUT_HINT}).",
    )
    screen_manager.update_last_question_message_id(message.from_user.id, sent.message_id)
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )


@router.message(ProfileStates.birth_time)
async def handle_profile_birth_time(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    screen_manager.add_user_message_id(message.from_user.id, message.message_id)
    await screen_manager.delete_last_question_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    birth_time = message.text or ""
    await state.update_data(birth_time=birth_time)
    await state.set_state(ProfileStates.birth_place)
    sent = await message.bot.send_message(
        chat_id=message.chat.id,
        text="Введите место рождения (в любом формате).",
    )
    screen_manager.update_last_question_message_id(message.from_user.id, sent.message_id)
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )


@router.message(ProfileStates.birth_place)
async def handle_profile_birth_place(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    screen_manager.add_user_message_id(message.from_user.id, message.message_id)
    await screen_manager.delete_last_question_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    birth_place = message.text or ""
    data = await state.get_data()
    with get_session() as session:
        user = _get_or_create_user(session, message.from_user.id, message.from_user.username)
        profile = user.profile
        if profile:
            profile.name = data["name"]
            profile.gender = data["gender"]
            profile.birth_date = data["birth_date"]
            profile.birth_time = data["birth_time"]
            profile.birth_place_city = birth_place
            profile.birth_place_region = None
            profile.birth_place_country = ""
        else:
            profile = UserProfile(
                user_id=user.id,
                name=data["name"],
                gender=data["gender"],
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
    await screen_manager.send_ephemeral_message(message, "Данные сохранены.")
    await screen_manager.show_screen(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        screen_id="S4_CONSENT",
    )
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )


@router.message(ProfileStates.edit_name)
async def handle_profile_edit_name(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    screen_manager.add_user_message_id(message.from_user.id, message.message_id)
    await screen_manager.delete_last_question_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    name = message.text or ""
    with get_session() as session:
        user = _get_or_create_user(session, message.from_user.id, message.from_user.username)
        profile = user.profile
        if not profile:
            await state.clear()
            await screen_manager.send_ephemeral_message(
                message, "Сначала заполните «Мои данные»."
            )
            await _show_profile_screen(message, message.from_user.id)
            return
        profile.name = name
        session.flush()
        screen_manager.update_state(
            message.from_user.id,
            **_profile_payload(profile),
        )
    await state.clear()
    await screen_manager.send_ephemeral_message(message, "Данные обновлены.")
    await _show_profile_screen(message, message.from_user.id)
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )


@router.message(ProfileStates.edit_birth_date)
async def handle_profile_edit_birth_date(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    screen_manager.add_user_message_id(message.from_user.id, message.message_id)
    await screen_manager.delete_last_question_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    birth_date = message.text or ""
    with get_session() as session:
        user = _get_or_create_user(session, message.from_user.id, message.from_user.username)
        profile = user.profile
        if not profile:
            await state.clear()
            await screen_manager.send_ephemeral_message(
                message, "Сначала заполните «Мои данные»."
            )
            await _show_profile_screen(message, message.from_user.id)
            return
        profile.birth_date = birth_date
        session.flush()
        screen_manager.update_state(
            message.from_user.id,
            **_profile_payload(profile),
        )
    await state.clear()
    await screen_manager.send_ephemeral_message(message, "Данные обновлены.")
    await _show_profile_screen(message, message.from_user.id)
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )


@router.message(ProfileStates.edit_gender)
async def handle_profile_edit_gender(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    screen_manager.add_user_message_id(message.from_user.id, message.message_id)
    await screen_manager.delete_last_question_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    gender = message.text or ""
    with get_session() as session:
        user = _get_or_create_user(session, message.from_user.id, message.from_user.username)
        profile = user.profile
        if not profile:
            await state.clear()
            await screen_manager.send_ephemeral_message(
                message, "Сначала заполните «Мои данные»."
            )
            await _show_profile_screen(message, message.from_user.id)
            return
        profile.gender = gender
        session.flush()
        screen_manager.update_state(
            message.from_user.id,
            **_profile_payload(profile),
        )
    await state.clear()
    await screen_manager.send_ephemeral_message(message, "Данные обновлены.")
    await _show_profile_screen(message, message.from_user.id)
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )


@router.message(ProfileStates.edit_birth_time)
async def handle_profile_edit_birth_time(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    screen_manager.add_user_message_id(message.from_user.id, message.message_id)
    await screen_manager.delete_last_question_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    birth_time = message.text or ""
    with get_session() as session:
        user = _get_or_create_user(session, message.from_user.id, message.from_user.username)
        profile = user.profile
        if not profile:
            await state.clear()
            await screen_manager.send_ephemeral_message(
                message, "Сначала заполните «Мои данные»."
            )
            await _show_profile_screen(message, message.from_user.id)
            return
        profile.birth_time = birth_time
        session.flush()
        screen_manager.update_state(
            message.from_user.id,
            **_profile_payload(profile),
        )
    await state.clear()
    await screen_manager.send_ephemeral_message(message, "Данные обновлены.")
    await _show_profile_screen(message, message.from_user.id)
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )


@router.message(ProfileStates.edit_birth_place)
async def handle_profile_edit_birth_place(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    screen_manager.add_user_message_id(message.from_user.id, message.message_id)
    await screen_manager.delete_last_question_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    birth_place = message.text or ""
    with get_session() as session:
        user = _get_or_create_user(session, message.from_user.id, message.from_user.username)
        profile = user.profile
        if not profile:
            await state.clear()
            await screen_manager.send_ephemeral_message(
                message, "Сначала заполните «Мои данные»."
            )
            await _show_profile_screen(message, message.from_user.id)
            return
        profile.birth_place_city = birth_place
        session.flush()
        screen_manager.update_state(
            message.from_user.id,
            **_profile_payload(profile),
        )
    await state.clear()
    await screen_manager.send_ephemeral_message(message, "Данные обновлены.")
    await _show_profile_screen(message, message.from_user.id)
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )
