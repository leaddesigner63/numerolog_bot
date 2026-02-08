from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.screen_manager import screen_manager

router = Router()


@router.message()
async def handle_unhandled_message(message: Message) -> None:
    if not message.from_user:
        return
    await screen_manager.show_screen(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        screen_id="S0",
        trigger_type="message",
        trigger_value="fallback_message",
    )
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )


@router.callback_query()
async def handle_unhandled_callback(callback: CallbackQuery) -> None:
    if not callback.from_user:
        return
    try:
        await callback.answer()
    except Exception:
        return
    if callback.message:
        await screen_manager.delete_screen_message(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            message_id=callback.message.message_id,
        )
