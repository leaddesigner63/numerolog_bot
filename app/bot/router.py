from aiogram import Dispatcher

from app.bot.handlers import feedback, profile, questionnaire, screen_images, screens, start, tariffs, fallback


def setup_bot_router(dispatcher: Dispatcher) -> None:
    dispatcher.include_router(start.router)
    dispatcher.include_router(tariffs.router)
    dispatcher.include_router(profile.router)
    dispatcher.include_router(questionnaire.router)
    dispatcher.include_router(feedback.router)
    dispatcher.include_router(screen_images.router)
    dispatcher.include_router(screens.router)
    dispatcher.include_router(fallback.router)
