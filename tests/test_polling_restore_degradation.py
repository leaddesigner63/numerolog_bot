import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.bot import polling


class PollingRestoreDegradationTests(unittest.IsolatedAsyncioTestCase):
    async def test_restore_error_does_not_interrupt_polling_startup(self) -> None:
        logger = MagicMock()
        dispatcher = MagicMock()
        dispatcher.start_polling = AsyncMock(return_value=None)

        with (
            patch.object(polling.logging, "getLogger", return_value=logger),
            patch.object(polling, "setup_logging"),
            patch.object(polling, "setup_bot_router"),
            patch.object(polling.settings, "bot_token", "test-token"),
            patch.object(polling, "Bot", return_value=MagicMock()),
            patch.object(polling, "Dispatcher", return_value=dispatcher),
            patch.object(polling, "restore_payment_waiters", new=AsyncMock(side_effect=RuntimeError("db is down"))),
            patch.object(polling.report_job_worker, "run", new=AsyncMock(return_value=None)),
        ):
            await polling.main()

        dispatcher.start_polling.assert_awaited_once()
        logger.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
