from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    await message.answer(
        "Добро пожаловать! Этот бот готовит аналитический отчёт по вашим данным.\n"
        "Выберите тариф или ознакомьтесь с офертой через меню."
    )
