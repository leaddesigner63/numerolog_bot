from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.types import Message

from app.bot.handlers.screen_manager import screen_manager
from app.bot.handlers.screens import FEEDBACK_SENT_NOTICE, _submit_feedback


FEEDBACK_SENT_NOTICE_DELETE_DELAY_SECONDS = 5

router = Router()


class IsFeedbackScreen(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if not message.from_user:
            return False
        state = screen_manager.update_state(message.from_user.id)
        return state.screen_id == "S8"


@router.message(IsFeedbackScreen(), F.text)
async def handle_feedback_text(message: Message) -> None:
    if not message.from_user:
        return
    screen_manager.add_user_message_id(message.from_user.id, message.message_id)
    feedback_text = message.text or ""
    screen_manager.update_state(message.from_user.id, feedback_text=feedback_text)
    status = await _submit_feedback(
        message.bot,
        user_id=message.from_user.id,
        username=message.from_user.username,
        feedback_text=feedback_text,
    )
    if status.name == "SENT":
        screen_manager.update_state(message.from_user.id, feedback_text=None)
        await screen_manager.send_ephemeral_message(
            message,
            FEEDBACK_SENT_NOTICE,
            delete_delay_seconds=FEEDBACK_SENT_NOTICE_DELETE_DELAY_SECONDS,
        )
    else:
        await screen_manager.send_ephemeral_message(
            message,
            "Не удалось отправить сообщение в админку. Попробуйте позже.",
        )
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )
