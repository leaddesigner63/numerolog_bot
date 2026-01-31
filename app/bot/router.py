from aiogram import Dispatcher

from app.bot.handlers import start, tariffs


def setup_bot_router(dispatcher: Dispatcher) -> None:
    dispatcher.include_router(start.router)
    dispatcher.include_router(tariffs.router)
