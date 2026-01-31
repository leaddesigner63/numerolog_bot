from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.bot.screen_manager import screen_manager

router = Router()


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    await screen_manager.show_screen(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        screen_id="S0",
    )
