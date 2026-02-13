from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.bot.questionnaire.config import (
    QuestionnaireQuestion,
    load_questionnaire_config,
    resolve_next_question_id,
)
from app.bot.handlers.profile import start_profile_wizard
from app.bot.handlers.screen_manager import screen_manager
from app.db.models import (
    Order,
    OrderStatus,
    QuestionnaireResponse,
    QuestionnaireStatus,
    Tariff,
    User,
    UserProfile,
)
from app.db.session import get_session

router = Router()
_TELEGRAM_MESSAGE_LIMIT = 4096


class QuestionnaireStates(StatesGroup):
    answering = State()


def _safe_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_or_create_user(
    session, telegram_user_id: int, telegram_username: str | None = None
) -> User:
    user = session.execute(
        select(User).where(User.telegram_user_id == telegram_user_id)
    ).scalar_one_or_none()
    if user:
        if telegram_username is not None:
            user.telegram_username = telegram_username
        return user

    user = User(telegram_user_id=telegram_user_id, telegram_username=telegram_username)
    session.add(user)
    session.flush()
    return user


def _build_keyboard(question: QuestionnaireQuestion) -> InlineKeyboardMarkup | None:
    if question.question_type == "choice":
        rows = [
            [
                InlineKeyboardButton(
                    text=_with_button_icons(option["label"], "🧩"),
                    callback_data=f"questionnaire:answer:{question.question_id}:{option['value']}",
                )
            ]
            for option in question.options
        ]
    elif question.question_type == "scale":
        min_value = int(question.scale.get("min", 1)) if question.scale else 1
        max_value = int(question.scale.get("max", 5)) if question.scale else 5
        rows = [
            [
                InlineKeyboardButton(
                    text=_with_button_icons(str(value), "🔢"),
                    callback_data=f"questionnaire:answer:{question.question_id}:{value}",
                )
                for value in range(min_value, max_value + 1)
            ]
        ]
    else:
        return None

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _with_button_icons(text: str, icon: str) -> str:
    clean_text = str(text).strip()
    return f"{icon} {clean_text}"


def _requires_text_input(question: QuestionnaireQuestion) -> bool:
    return question.question_type == "text"


def _question_payload(
    response: QuestionnaireResponse | None, config_version: str
) -> dict[str, Any]:
    if not response:
        return {
            "questionnaire": {
                "version": config_version,
                "status": "empty",
                "answers": {},
                "current_question_id": None,
                "answered_count": 0,
                "total_questions": 0,
                "completed_at": None,
            }
        }
    answers = response.answers or {}
    return {
        "questionnaire": {
            "version": response.questionnaire_version,
            "status": response.status.value,
            "answers": answers,
            "current_question_id": response.current_question_id,
            "answered_count": len(answers),
            "total_questions": 0,
            "completed_at": response.completed_at.isoformat() if response.completed_at else None,
        }
    }


def _update_screen_state(user_id: int, payload: dict[str, Any]) -> None:
    screen_manager.update_state(user_id, **payload)


def _split_text_by_length(text: str, max_length: int) -> list[str]:
    if max_length <= 0:
        return [text]
    if not text:
        return [""]
    return [text[index : index + max_length] for index in range(0, len(text), max_length)]


def _build_answers_summary_messages(
    *,
    config,
    answers: dict[str, Any] | None,
    max_length: int = _TELEGRAM_MESSAGE_LIMIT,
) -> list[str]:
    current_answers = answers or {}
    summary_items: list[str] = []
    for index, question in enumerate(config.questions.values(), start=1):
        has_answer = question.question_id in current_answers
        answer_text = current_answers.get(question.question_id)
        rendered_answer = str(answer_text) if has_answer and answer_text is not None else "(пусто)"
        summary_items.append(
            f"{index}. {question.text}\n"
            f"Текущий ответ: {rendered_answer}"
        )

    if not summary_items:
        return []

    chunks: list[str] = []
    current_chunk = ""
    for item in summary_items:
        candidate = item if not current_chunk else f"{current_chunk}\n\n{item}"
        if len(candidate) <= max_length:
            current_chunk = candidate
            continue
        if current_chunk:
            chunks.append(current_chunk)
            current_chunk = ""
        if len(item) <= max_length:
            current_chunk = item
            continue
        chunks.extend(_split_text_by_length(item, max_length))

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def _render_existing_answer(answer: Any) -> str:
    if answer is None:
        return "(пусто)"
    answer_text = str(answer)
    if answer_text == "":
        return "(пусто)"
    return answer_text


def _build_edit_decision_message(question_text: str, existing_answer: Any) -> str:
    return (
        f"Текущий ответ:\n{_render_existing_answer(existing_answer)}\n\n"
        "Подсказка: нажмите кнопку «📋 Редактировать текущий ответ», "
        "чтобы бот подставил текущий ответ в текстовое поле.\n\n"
        "Действие: выберите, оставить текущий ответ или изменить."
        f"\n\n{question_text}"
    )


def _build_edit_change_message(
    question_text: str,
    existing_answer: Any,
    *,
    show_copy_hint: bool,
) -> str:
    hint_block = (
        "Подсказка: нажмите кнопку «📋 Редактировать текущий ответ», "
        "чтобы бот подставил текущий ответ в текстовое поле.\n\n"
        if show_copy_hint
        else ""
    )
    return (
        f"Текущий ответ:\n{_render_existing_answer(existing_answer)}\n\n"
        f"{hint_block}"
        "Действие: отправьте новый ответ."
        f"\n\n{question_text}"
    )


def _copy_button_for_answer(existing_answer: Any) -> InlineKeyboardButton | None:
    if existing_answer is None:
        return None
    answer_text = str(existing_answer)
    if answer_text == "":
        return None
    return InlineKeyboardButton(
        text=_with_button_icons("Редактировать текущий ответ", "📋"),
        switch_inline_query_current_chat=answer_text,
    )


def _build_edit_decision_keyboard(existing_answer: Any) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    copy_button = _copy_button_for_answer(existing_answer)
    if copy_button:
        rows.append([copy_button])
    rows.append(
        [
            InlineKeyboardButton(
                text=_with_button_icons("Оставить текущий ответ", "✅"),
                callback_data="questionnaire:edit_action:keep",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)




def _build_delete_questionnaire_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Да, удалить анкету", "✅"),
                    callback_data="questionnaire:delete:lk:confirm",
                )
            ],
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Отмена", "❌"),
                    callback_data="questionnaire:delete:lk:cancel",
                )
            ],
        ]
    )

def _build_copy_answer_keyboard(existing_answer: Any) -> InlineKeyboardMarkup | None:
    copy_button = _copy_button_for_answer(existing_answer)
    if not copy_button:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[copy_button]])


def _build_actual_answers(
    *,
    config,
    raw_answers: dict[str, Any] | None,
) -> tuple[dict[str, Any], str | None]:
    """Возвращает только актуальные ответы по валидной ветке анкеты."""
    answers = raw_answers or {}
    actual: dict[str, Any] = {}
    current_question_id = config.start_question_id
    visited: set[str] = set()

    while current_question_id and current_question_id not in visited:
        question = config.get_question(current_question_id)
        if not question:
            return actual, None
        visited.add(current_question_id)
        if current_question_id not in answers:
            return actual, current_question_id

        answer = answers[current_question_id]
        actual[current_question_id] = answer
        next_question_id = resolve_next_question_id(question, str(answer))
        if next_question_id and next_question_id not in config.questions:
            next_question_id = None
        current_question_id = next_question_id

    return actual, current_question_id


async def _ensure_paid_access(callback: CallbackQuery) -> bool:
    state_snapshot = screen_manager.update_state(callback.from_user.id)
    selected_tariff = state_snapshot.data.get("selected_tariff")
    if selected_tariff not in {Tariff.T2.value, Tariff.T3.value}:
        await screen_manager.send_ephemeral_message(
            callback.message,
            "Анкета доступна только для тарифов T2 и T3.",
            user_id=callback.from_user.id,
        )
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id="S1",
        )
        return False

    order_id = _safe_int(state_snapshot.data.get("order_id"))
    if not order_id:
        await screen_manager.send_ephemeral_message(
            callback.message,
            "Сначала выберите тариф и завершите оплату.",
            user_id=callback.from_user.id,
        )
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id="S3",
        )
        return False

    with get_session() as session:
        order = session.get(Order, order_id)
        if order:
            screen_manager.update_state(
                callback.from_user.id,
                order_id=str(order.id),
                order_status=order.status.value,
                order_amount=str(order.amount),
                order_currency=order.currency,
            )
        if not order or order.status != OrderStatus.PAID:
            await screen_manager.send_ephemeral_message(
                callback.message,
                "Оплата ещё не подтверждена. Доступ к анкете откроется после статуса paid.",
                user_id=callback.from_user.id,
            )
            await screen_manager.show_screen(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                user_id=callback.from_user.id,
                screen_id="S3",
            )
            return False
    return True


async def _ensure_profile_ready(callback: CallbackQuery, state: FSMContext) -> bool:
    with get_session() as session:
        user = _get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        profile = session.execute(
            select(UserProfile).where(UserProfile.user_id == user.id)
        ).scalar_one_or_none()

    if profile:
        return True

    await screen_manager.send_ephemeral_message(
        callback.message,
        "Сначала заполните «Мои данные».",
        user_id=callback.from_user.id,
    )
    await screen_manager.show_screen(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        screen_id="S4",
    )
    await start_profile_wizard(callback.message, state, callback.from_user.id)
    return False


def _upsert_progress(
    session,
    *,
    user_id: int,
    config_version: str,
    answers: dict[str, Any],
    current_question_id: str | None,
    status: QuestionnaireStatus,
    completed_at: datetime | None,
) -> QuestionnaireResponse:
    response = session.execute(
        select(QuestionnaireResponse).where(
            QuestionnaireResponse.user_id == user_id,
            QuestionnaireResponse.questionnaire_version == config_version,
        )
    ).scalar_one_or_none()

    if response:
        response.answers = answers
        response.current_question_id = current_question_id
        response.status = status
        response.completed_at = completed_at
    else:
        response = QuestionnaireResponse(
            user_id=user_id,
            questionnaire_version=config_version,
            answers=answers,
            current_question_id=current_question_id,
            status=status,
            completed_at=completed_at,
        )
        session.add(response)

    session.flush()
    return response


async def _send_question(
    *,
    message: Message,
    user_id: int,
    question: QuestionnaireQuestion | None,
    existing_answer: Any | None = None,
    show_edit_actions: bool = False,
    force_input: bool = False,
) -> None:
    if not question:
        await screen_manager.send_ephemeral_message(
            message,
            "Не удалось загрузить вопрос анкеты. Попробуйте начать заново через «Заполнить анкету».",
        )
        return
    await screen_manager.delete_last_question_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=user_id,
    )
    if show_edit_actions:
        keyboard = _build_edit_decision_keyboard(existing_answer)
        question_text = _build_edit_decision_message(question.text, existing_answer)
    else:
        keyboard = _build_keyboard(question)
        if _requires_text_input(question):
            keyboard = None
        show_copy_hint = (
            keyboard is None
            and existing_answer is not None
            and not _requires_text_input(question)
        )
        if existing_answer is not None:
            question_text = _build_edit_change_message(
                question.text,
                existing_answer,
                show_copy_hint=show_copy_hint,
            )
            if keyboard is None and not _requires_text_input(question):
                keyboard = _build_copy_answer_keyboard(existing_answer)
        else:
            question_text = question.text

    if force_input:
        keyboard = _build_keyboard(question)
        question_text = _build_edit_change_message(
            question.text,
            existing_answer,
            show_copy_hint=False,
        )
    if keyboard is None:
        await screen_manager.enter_text_input_mode(
            bot=message.bot,
            chat_id=message.chat.id,
            user_id=user_id,
            preserve_last_question=True,
        )
    sent = await message.bot.send_message(
        chat_id=message.chat.id,
        text=question_text,
        reply_markup=keyboard,
    )
    screen_manager.update_last_question_message_id(user_id, sent.message_id)


async def _restore_state_from_db(
    *,
    message: Message,
    state: FSMContext,
    config_version: str,
    fallback_question_id: str | None,
) -> dict[str, Any]:
    with get_session() as session:
        user = _get_or_create_user(session, message.from_user.id, message.from_user.username)
        response = session.execute(
            select(QuestionnaireResponse).where(
                QuestionnaireResponse.user_id == user.id,
                QuestionnaireResponse.questionnaire_version == config_version,
            )
        ).scalar_one_or_none()
    if response:
        config = load_questionnaire_config()
        answers, actual_current_question_id = _build_actual_answers(
            config=config,
            raw_answers=response.answers,
        )
        current_question_id = actual_current_question_id or fallback_question_id
        await state.set_state(QuestionnaireStates.answering)
        await state.update_data(
            questionnaire_version=config_version,
            current_question_id=current_question_id,
            answers=answers,
        )
        return {
            "current_question_id": current_question_id,
            "answers": answers,
        }
    return {}


def _refresh_questionnaire_state(user_id: int, telegram_username: str | None = None) -> None:
    config = load_questionnaire_config()
    with get_session() as session:
        user = _get_or_create_user(session, user_id, telegram_username)
        response = session.execute(
            select(QuestionnaireResponse).where(
                QuestionnaireResponse.user_id == user.id,
                QuestionnaireResponse.questionnaire_version == config.version,
            )
        ).scalar_one_or_none()
        payload = _question_payload(response, config.version)
        payload["questionnaire"]["total_questions"] = len(config.questions)
    _update_screen_state(user_id, payload)


async def _start_edit_questionnaire(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    return_screen_id: str,
) -> None:
    config = load_questionnaire_config()
    with get_session() as session:
        user = _get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        response = session.execute(
            select(QuestionnaireResponse).where(
                QuestionnaireResponse.user_id == user.id,
                QuestionnaireResponse.questionnaire_version == config.version,
            )
        ).scalar_one_or_none()
        answers, current_question_id = _build_actual_answers(
            config=config,
            raw_answers=response.answers if response and response.answers else {},
        )
        if not current_question_id:
            current_question_id = config.start_question_id
        response = _upsert_progress(
            session,
            user_id=user.id,
            config_version=config.version,
            answers=answers,
            current_question_id=current_question_id,
            status=QuestionnaireStatus.IN_PROGRESS,
            completed_at=None,
        )
        payload = _question_payload(response, config.version)
        payload["questionnaire"]["total_questions"] = len(config.questions)

    await state.set_state(QuestionnaireStates.answering)
    await state.update_data(
        questionnaire_version=config.version,
        current_question_id=current_question_id,
        answers=answers,
        questionnaire_mode="edit",
        questionnaire_return_screen=return_screen_id,
    )
    await _send_question(
        message=callback.message,
        user_id=callback.from_user.id,
        question=config.get_question(current_question_id),
        existing_answer=answers.get(current_question_id),
        show_edit_actions=True,
    )
    _update_screen_state(callback.from_user.id, payload)


@router.callback_query(F.data == "questionnaire:start")
async def start_questionnaire(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_paid_access(callback):
        await callback.answer()
        return
    if not await _ensure_profile_ready(callback, state):
        await callback.answer()
        return
    config = load_questionnaire_config()
    with get_session() as session:
        user = _get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        response = session.execute(
            select(QuestionnaireResponse).where(
                QuestionnaireResponse.user_id == user.id,
                QuestionnaireResponse.questionnaire_version == config.version,
            )
        ).scalar_one_or_none()

        if response and response.status == QuestionnaireStatus.COMPLETED:
            await screen_manager.send_ephemeral_message(
                callback.message,
                "Анкета уже заполнена. Нажмите «Редактировать анкету», чтобы внести изменения.",
                user_id=callback.from_user.id,
            )
            await callback.answer()
            payload = _question_payload(response, config.version)
            payload["questionnaire"]["total_questions"] = len(config.questions)
            _update_screen_state(callback.from_user.id, payload)
            return

        answers = response.answers if response and response.answers else {}
        answers, default_current_question_id = _build_actual_answers(
            config=config,
            raw_answers=answers,
        )
        if response and default_current_question_id is None and answers:
            completed_at = response.completed_at or datetime.now(timezone.utc)
            response = _upsert_progress(
                session,
                user_id=user.id,
                config_version=config.version,
                answers=answers,
                current_question_id=None,
                status=QuestionnaireStatus.COMPLETED,
                completed_at=completed_at,
            )
            await screen_manager.send_ephemeral_message(
                callback.message,
                "Анкета уже заполнена. Нажмите «Продолжить», чтобы перейти к генерации.",
                user_id=callback.from_user.id,
            )
            await callback.answer()
            payload = _question_payload(response, config.version)
            payload["questionnaire"]["total_questions"] = len(config.questions)
            _update_screen_state(callback.from_user.id, payload)
            return
        current_question_id = default_current_question_id or config.start_question_id
        response = _upsert_progress(
            session,
            user_id=user.id,
            config_version=config.version,
            answers=answers,
            current_question_id=current_question_id,
            status=QuestionnaireStatus.IN_PROGRESS,
            completed_at=None,
        )
        payload = _question_payload(response, config.version)
        payload["questionnaire"]["total_questions"] = len(config.questions)

    await state.set_state(QuestionnaireStates.answering)
    await state.update_data(
        questionnaire_version=config.version,
        current_question_id=current_question_id,
        answers=answers,
        questionnaire_mode="start",
        questionnaire_return_screen="S5",
    )
    await _send_question(
        message=callback.message,
        user_id=callback.from_user.id,
        question=config.get_question(current_question_id),
    )
    _update_screen_state(callback.from_user.id, payload)
    await callback.answer()


@router.callback_query(F.data == "questionnaire:restart")
async def restart_questionnaire(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_paid_access(callback):
        await callback.answer()
        return
    if not await _ensure_profile_ready(callback, state):
        await callback.answer()
        return
    config = load_questionnaire_config()
    with get_session() as session:
        user = _get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        response = _upsert_progress(
            session,
            user_id=user.id,
            config_version=config.version,
            answers={},
            current_question_id=config.start_question_id,
            status=QuestionnaireStatus.IN_PROGRESS,
            completed_at=None,
        )
        payload = _question_payload(response, config.version)
        payload["questionnaire"]["total_questions"] = len(config.questions)

    await state.set_state(QuestionnaireStates.answering)
    await state.update_data(
        questionnaire_version=config.version,
        current_question_id=config.start_question_id,
        answers={},
        questionnaire_mode="restart",
        questionnaire_return_screen="S5",
    )
    await _send_question(
        message=callback.message,
        user_id=callback.from_user.id,
        question=config.get_question(config.start_question_id),
    )
    _update_screen_state(callback.from_user.id, payload)
    await callback.answer()


@router.callback_query(F.data == "questionnaire:edit")
async def edit_questionnaire(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_paid_access(callback):
        await callback.answer()
        return
    if not await _ensure_profile_ready(callback, state):
        await callback.answer()
        return
    await _start_edit_questionnaire(
        callback,
        state,
        return_screen_id="S5",
    )
    await callback.answer()


@router.callback_query(F.data == "questionnaire:edit:lk")
async def edit_questionnaire_from_lk(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_paid_access(callback):
        await callback.answer()
        return
    if not await _ensure_profile_ready(callback, state):
        await callback.answer()
        return
    await _start_edit_questionnaire(
        callback,
        state,
        return_screen_id="S11",
    )
    await callback.answer()


@router.callback_query(F.data == "questionnaire:answers:expand")
async def expand_questionnaire_answers_from_lk(callback: CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return
    screen_manager.update_state(callback.from_user.id, questionnaire_answers_expanded=True)
    await screen_manager.show_screen(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        screen_id="S11",
    )
    await callback.answer()


@router.callback_query(F.data == "questionnaire:answers:collapse")
async def collapse_questionnaire_answers_from_lk(callback: CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return
    screen_manager.update_state(callback.from_user.id, questionnaire_answers_expanded=False)
    await screen_manager.show_screen(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        screen_id="S11",
    )
    await callback.answer()

@router.callback_query(F.data == "questionnaire:delete:lk")
async def delete_questionnaire_from_lk(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_paid_access(callback):
        await callback.answer()
        return
    if not await _ensure_profile_ready(callback, state):
        await callback.answer()
        return
    await screen_manager.send_ephemeral_message(
        callback.message,
        "Вы уверены, что хотите удалить расширенную анкету?",
        reply_markup=_build_delete_questionnaire_confirm_keyboard(),
        user_id=callback.from_user.id,
    )
    await callback.answer()


@router.callback_query(F.data == "questionnaire:delete:lk:cancel")
async def cancel_delete_questionnaire_from_lk(callback: CallbackQuery) -> None:
    await screen_manager.show_screen(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        screen_id="S11",
    )
    await callback.answer("Удаление отменено.")


@router.callback_query(F.data == "questionnaire:delete:lk:confirm")
async def confirm_delete_questionnaire_from_lk(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_paid_access(callback):
        await callback.answer()
        return
    if not await _ensure_profile_ready(callback, state):
        await callback.answer()
        return
    config = load_questionnaire_config()
    with get_session() as session:
        user = _get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        response = session.execute(
            select(QuestionnaireResponse).where(
                QuestionnaireResponse.user_id == user.id,
                QuestionnaireResponse.questionnaire_version == config.version,
            )
        ).scalar_one_or_none()
        if response:
            session.delete(response)
            session.flush()
    await state.clear()
    _refresh_questionnaire_state(callback.from_user.id, callback.from_user.username)
    screen_manager.update_state(callback.from_user.id, questionnaire_answers_expanded=False)
    await screen_manager.show_screen(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        screen_id="S11",
    )
    await callback.answer("Анкета удалена.")


@router.callback_query(F.data == "questionnaire:edit_action:keep")
async def keep_current_edit_answer(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    data = await state.get_data()
    current_question_id = data.get("current_question_id")
    answers = dict(data.get("answers") or {})
    if not current_question_id:
        await screen_manager.send_ephemeral_message(
            callback.message, "Анкета не активна. Нажмите «Заполнить анкету»."
        )
        await callback.answer()
        return
    answer = answers.get(current_question_id, "")
    await screen_manager.delete_last_question_message(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
    )
    await _handle_answer(
        message=callback.message,
        state=state,
        answer=str(answer),
        question_id=current_question_id,
    )
    await callback.answer()


@router.callback_query(F.data == "questionnaire:edit_action:change")
async def change_current_edit_answer(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    data = await state.get_data()
    current_question_id = data.get("current_question_id")
    answers = dict(data.get("answers") or {})
    if not current_question_id:
        await screen_manager.send_ephemeral_message(
            callback.message, "Анкета не активна. Нажмите «Заполнить анкету»."
        )
        await callback.answer()
        return
    config = load_questionnaire_config()
    await _send_question(
        message=callback.message,
        user_id=callback.from_user.id,
        question=config.get_question(current_question_id),
        existing_answer=answers.get(current_question_id),
        force_input=True,
    )
    await callback.answer()


@router.callback_query(F.data == "questionnaire:copy_current_answer")
async def copy_current_answer(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    data = await state.get_data()
    current_question_id = data.get("current_question_id")
    answers = dict(data.get("answers") or {})
    answer_text = str(answers.get(current_question_id, ""))
    if answer_text == "":
        await callback.answer("Текущий ответ пустой.", show_alert=False)
        return

    await callback.message.answer(
        f"Текущий ответ:\n{answer_text}",
    )
    await callback.answer("Ответ отправлен отдельным сообщением.", show_alert=False)


async def _handle_answer(
    *,
    message: Message,
    state: FSMContext,
    answer: str,
    question_id: str | None = None,
) -> None:
    config = load_questionnaire_config()
    data = await state.get_data()
    questionnaire_mode = data.get("questionnaire_mode")
    questionnaire_return_screen = data.get("questionnaire_return_screen") or "S5"
    current_question_id = data.get("current_question_id")
    if not current_question_id:
        restored = await _restore_state_from_db(
            message=message,
            state=state,
            config_version=config.version,
            fallback_question_id=config.start_question_id,
        )
        current_question_id = restored.get("current_question_id")
        data = {**data, **restored}
    if question_id and question_id != current_question_id:
        await screen_manager.send_ephemeral_message(
            message, "Этот вопрос уже не актуален. Пожалуйста, продолжите текущий шаг."
        )
        return
    if not current_question_id:
        await screen_manager.send_ephemeral_message(
            message, "Анкета не активна. Нажмите «Заполнить анкету»."
        )
        return

    question = config.get_question(current_question_id)
    if not question:
        await screen_manager.send_ephemeral_message(
            message,
            "Не удалось найти текущий вопрос анкеты. Попробуйте начать заполнение заново.",
        )
        return
    answers = dict(data.get("answers", {}))
    actual_answers, expected_question_id = _build_actual_answers(
        config=config,
        raw_answers=answers,
    )
    if expected_question_id and expected_question_id != current_question_id:
        current_question_id = expected_question_id
        question = config.get_question(current_question_id)
        if not question:
            await screen_manager.send_ephemeral_message(
                message,
                "Анкета временно недоступна. Запустите заполнение заново.",
            )
            return
    answers = actual_answers
    answers[current_question_id] = answer
    next_question_id = resolve_next_question_id(question, answer)

    completed_at = None
    status = QuestionnaireStatus.IN_PROGRESS
    if next_question_id and next_question_id not in config.questions:
        next_question_id = None
    if next_question_id is None:
        status = QuestionnaireStatus.COMPLETED
        completed_at = datetime.now(timezone.utc)

    with get_session() as session:
        user = _get_or_create_user(session, message.from_user.id, message.from_user.username)
        response = _upsert_progress(
            session,
            user_id=user.id,
            config_version=config.version,
            answers=answers,
            current_question_id=next_question_id,
            status=status,
            completed_at=completed_at,
        )
        payload = _question_payload(response, config.version)
        payload["questionnaire"]["total_questions"] = len(config.questions)

    await state.update_data(
        answers=answers,
        current_question_id=next_question_id,
    )
    _update_screen_state(message.from_user.id, payload)

    if status == QuestionnaireStatus.COMPLETED:
        await state.clear()
        done_callback_data = "questionnaire:done"
        if questionnaire_mode in {"edit", "restart"}:
            done_callback_data = f"screen:{questionnaire_return_screen}"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_with_button_icons("Готово", "✅"),
                        callback_data=done_callback_data,
                    )
                ]
            ]
        )
        await screen_manager.send_ephemeral_message(
            message,
            "Анкета заполнена. Нажмите «Готово», чтобы продолжить.",
            reply_markup=keyboard,
        )
        return

    await _send_question(
        message=message,
        user_id=message.from_user.id,
        question=config.get_question(next_question_id),
        existing_answer=answers.get(next_question_id) if questionnaire_mode == "edit" else None,
        show_edit_actions=questionnaire_mode == "edit",
    )


@router.callback_query(F.data.startswith("questionnaire:answer:"))
async def handle_choice_answer(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":", maxsplit=3)
    if len(parts) < 4:
        await callback.answer()
        return
    _, _, question_id, value = parts
    if callback.message:
        await screen_manager.delete_last_question_message(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
        )
    await _handle_answer(message=callback.message, state=state, answer=value, question_id=question_id)
    await callback.answer()


@router.message(QuestionnaireStates.answering)
async def handle_text_answer(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    screen_manager.add_user_message_id(message.from_user.id, message.message_id)
    await screen_manager.delete_last_question_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    await _handle_answer(message=message, state=state, answer=message.text or "")
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )
