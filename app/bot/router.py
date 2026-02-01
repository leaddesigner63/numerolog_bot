from aiogram import Dispatcher

from app.bot.handlers import feedback, profile, questionnaire, screens, start, tariffs


def setup_bot_router(dispatcher: Dispatcher) -> None:
    dispatcher.include_router(start.router)
    dispatcher.include_router(tariffs.router)
    dispatcher.include_router(profile.router)
    dispatcher.include_router(questionnaire.router)
    dispatcher.include_router(feedback.router)
    dispatcher.include_router(screens.router)
