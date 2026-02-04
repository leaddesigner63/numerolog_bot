from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.types import Message

from app.bot.handlers.screen_manager import screen_manager
from app.core.config import settings


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
    if (settings.feedback_mode or "native").lower() == "livegram":
        if settings.feedback_group_url:
            await message.answer(
                "Сообщение сохранено. В режиме livegram нажмите «Перейти в группу», "
                "чтобы отправить его."
            )
        else:
            await message.answer(
                "Сообщение сохранено, но ссылка на группу для livegram не настроена."
            )
        return
    await message.answer("Сообщение сохранено. Нажмите «Отправить», чтобы опубликовать его.")
