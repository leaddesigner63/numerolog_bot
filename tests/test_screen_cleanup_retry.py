import unittest
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest

from app.bot.handlers.screen_manager import ScreenManager


class ScreenCleanupRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_delete_message_eventually_succeeds(self) -> None:
        manager = ScreenManager()
        bot = AsyncMock()
        bot.delete_message.side_effect = [
            TelegramBadRequest(method="deleteMessage", message="Bad Request: message can't be deleted"),
            None,
        ]

        result = await manager._retry_delete_message(
            bot,
            chat_id=1,
            message_id=10,
            attempts=2,
            delay_seconds=0,
        )

        self.assertTrue(result)
        self.assertEqual(bot.delete_message.await_count, 2)


if __name__ == "__main__":
    unittest.main()
