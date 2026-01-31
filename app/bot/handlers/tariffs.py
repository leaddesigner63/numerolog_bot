from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("tariffs"))
async def handle_tariffs(message: Message) -> None:
    await message.answer(
        "Тарифы:\n"
        "T0 — 0 ₽ (демо, 1 раз в месяц)\n"
        "T1 — 560 ₽\n"
        "T2 — 2190 ₽\n"
        "T3 — 5930 ₽\n"
        "Полный экранный флоу будет добавлен в следующих итерациях."
    )
