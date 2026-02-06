import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.router import setup_bot_router
from app.core.config import settings
from app.core.logging import setup_logging


async def main() -> None:
    setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    if not settings.bot_token:
        logger.error("bot_token_missing")
        return
    bot = Bot(token=settings.bot_token)
    dispatcher = Dispatcher(storage=MemoryStorage())
    setup_bot_router(dispatcher)

    logger.info("Starting bot polling")
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
