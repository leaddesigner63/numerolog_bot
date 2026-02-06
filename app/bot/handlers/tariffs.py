from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.handlers.screen_manager import screen_manager

router = Router()


@router.message(Command("tariffs"))
async def handle_tariffs(message: Message) -> None:
    if not message.from_user:
        return
    await screen_manager.show_screen(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        screen_id="S1",
    )
    await screen_manager.delete_user_message(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        message_id=message.message_id,
    )
