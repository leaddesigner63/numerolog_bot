import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.router import setup_bot_router
from app.bot.report_jobs_worker import report_job_worker
from app.bot.handlers.screens import restore_payment_waiters
from app.core.config import log_payment_runtime_snapshot, settings
from app.core.logging import setup_logging


async def main() -> None:
    setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    log_payment_runtime_snapshot(logger)
    if not settings.bot_token:
        logger.error("bot_token_missing")
        return
    bot = Bot(token=settings.bot_token)
    dispatcher = Dispatcher(storage=MemoryStorage())
    setup_bot_router(dispatcher)

    try:
        await restore_payment_waiters(bot)
    except Exception as exc:
        logger.warning(
            "payment_waiters_restore_failed",
            extra={"event_code": "payment_waiters_restore_failed", "error": str(exc)},
        )

    logger.info("Starting bot polling")
    worker_task = asyncio.create_task(report_job_worker.run(bot))
    try:
        await dispatcher.start_polling(bot)
    finally:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task


if __name__ == "__main__":
    asyncio.run(main())
