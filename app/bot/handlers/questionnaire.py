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
from app.bot.handlers.screen_manager import screen_manager
from app.db.models import QuestionnaireResponse, QuestionnaireStatus, User
from app.db.session import get_session

router = Router()


class QuestionnaireStates(StatesGroup):
    answering = State()


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


def _build_keyboard(question: QuestionnaireQuestion) -> InlineKeyboardMarkup | None:
    if question.question_type == "choice":
        rows = [
            [
                InlineKeyboardButton(
                    text=option["label"],
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
                    text=str(value),
                    callback_data=f"questionnaire:answer:{question.question_id}:{value}",
                )
                for value in range(min_value, max_value + 1)
            ]
        ]
    else:
        return None

    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def _update_screen_state(user_id: int, response: QuestionnaireResponse | None) -> None:
    config = load_questionnaire_config()
    payload = _question_payload(response, config.version)
    payload["questionnaire"]["total_questions"] = len(config.questions)
    screen_manager.update_state(user_id, **payload)


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
    question: QuestionnaireQuestion,
) -> None:
    keyboard = _build_keyboard(question)
    await message.answer(question.text, reply_markup=keyboard)


@router.callback_query(F.data == "questionnaire:start")
async def start_questionnaire(callback: CallbackQuery, state: FSMContext) -> None:
    config = load_questionnaire_config()
    with get_session() as session:
        user = _get_or_create_user(session, callback.from_user.id)
        response = session.execute(
            select(QuestionnaireResponse).where(
                QuestionnaireResponse.user_id == user.id,
                QuestionnaireResponse.questionnaire_version == config.version,
            )
        ).scalar_one_or_none()

        if response and response.status == QuestionnaireStatus.COMPLETED:
            await callback.message.answer(
                "Анкета уже заполнена. Нажмите «Сбросить», если хотите пройти её заново."
            )
            await callback.answer()
            _update_screen_state(callback.from_user.id, response)
            return

        answers = response.answers if response and response.answers else {}
        if response and response.current_question_id:
            current_question_id = response.current_question_id
        else:
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

    await state.set_state(QuestionnaireStates.answering)
    await state.update_data(
        questionnaire_version=config.version,
        current_question_id=current_question_id,
        answers=answers,
    )
    await _send_question(message=callback.message, question=config.get_question(current_question_id))
    _update_screen_state(callback.from_user.id, response)
    await callback.answer()


@router.callback_query(F.data == "questionnaire:restart")
async def restart_questionnaire(callback: CallbackQuery, state: FSMContext) -> None:
    config = load_questionnaire_config()
    with get_session() as session:
        user = _get_or_create_user(session, callback.from_user.id)
        response = _upsert_progress(
            session,
            user_id=user.id,
            config_version=config.version,
            answers={},
            current_question_id=config.start_question_id,
            status=QuestionnaireStatus.IN_PROGRESS,
            completed_at=None,
        )

    await state.set_state(QuestionnaireStates.answering)
    await state.update_data(
        questionnaire_version=config.version,
        current_question_id=config.start_question_id,
        answers={},
    )
    await _send_question(message=callback.message, question=config.get_question(config.start_question_id))
    _update_screen_state(callback.from_user.id, response)
    await callback.answer()


def _validate_answer(question: QuestionnaireQuestion, answer: str) -> tuple[bool, Any, str | None]:
    if question.question_type == "text":
        cleaned = answer.strip()
        if question.required and not cleaned:
            return False, None, "Ответ не может быть пустым."
        return True, cleaned, None
    if question.question_type == "choice":
        allowed = {option["value"] for option in question.options}
        if answer not in allowed:
            return False, None, "Выберите вариант из списка кнопок."
        return True, answer, None
    if question.question_type == "scale":
        if not answer.isdigit():
            return False, None, "Выберите число из шкалы."
        value = int(answer)
        min_value = int(question.scale.get("min", 1)) if question.scale else 1
        max_value = int(question.scale.get("max", 5)) if question.scale else 5
        if value < min_value or value > max_value:
            return False, None, "Значение вне диапазона шкалы."
        return True, value, None
    return False, None, "Неизвестный тип вопроса."


async def _handle_answer(
    *,
    message: Message,
    state: FSMContext,
    answer: str,
    question_id: str | None = None,
) -> None:
    config = load_questionnaire_config()
    data = await state.get_data()
    current_question_id = data.get("current_question_id")
    if question_id and question_id != current_question_id:
        await message.answer("Этот вопрос уже не актуален. Пожалуйста, продолжите текущий шаг.")
        return
    if not current_question_id:
        await message.answer("Анкета не активна. Нажмите «Заполнить анкету».")
        return

    question = config.get_question(current_question_id)
    is_valid, normalized, error = _validate_answer(question, answer)
    if not is_valid:
        await message.answer(error or "Некорректный ответ.")
        return

    answers = dict(data.get("answers", {}))
    answers[current_question_id] = normalized
    next_question_id = resolve_next_question_id(question, normalized)

    completed_at = None
    status = QuestionnaireStatus.IN_PROGRESS
    if next_question_id is None:
        status = QuestionnaireStatus.COMPLETED
        completed_at = datetime.now(timezone.utc)

    with get_session() as session:
        user = _get_or_create_user(session, message.from_user.id)
        response = _upsert_progress(
            session,
            user_id=user.id,
            config_version=config.version,
            answers=answers,
            current_question_id=next_question_id,
            status=status,
            completed_at=completed_at,
        )

    await state.update_data(
        answers=answers,
        current_question_id=next_question_id,
    )
    _update_screen_state(message.from_user.id, response)

    if status == QuestionnaireStatus.COMPLETED:
        await state.clear()
        await message.answer("Анкета заполнена. Нажмите «Готово», чтобы продолжить.")
        return

    await _send_question(message=message, question=config.get_question(next_question_id))


@router.callback_query(F.data.startswith("questionnaire:answer:"))
async def handle_choice_answer(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":", maxsplit=3)
    if len(parts) < 4:
        await callback.answer()
        return
    _, _, question_id, value = parts
    await _handle_answer(message=callback.message, state=state, answer=value, question_id=question_id)
    await callback.answer()


@router.message(QuestionnaireStates.answering)
async def handle_text_answer(message: Message, state: FSMContext) -> None:
    await _handle_answer(message=message, state=state, answer=message.text or "")
