import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramNetworkError

from app.bot.handlers.screens import _safe_callback_answer, _safe_callback_processing


class CallbackAnswerResilienceTests(unittest.IsolatedAsyncioTestCase):
    def _build_callback(self) -> SimpleNamespace:
        return SimpleNamespace(
            answered=False,
            from_user=SimpleNamespace(id=123),
            answer=AsyncMock(),
        )

    async def test_safe_callback_answer_swallows_network_errors(self) -> None:
        callback = self._build_callback()
        callback.answer.side_effect = TelegramNetworkError(
            method="answerCallbackQuery",
            message="Request timeout error",
        )

        await _safe_callback_answer(callback)

        callback.answer.assert_awaited_once_with()
        self.assertFalse(getattr(callback, "_answered", False))

    async def test_safe_callback_processing_swallows_network_errors(self) -> None:
        callback = self._build_callback()
        callback.answer.side_effect = TimeoutError("network timeout")

        await _safe_callback_processing(callback)

        callback.answer.assert_awaited_once_with("Обрабатываю…")
        self.assertFalse(getattr(callback, "_answered", False))


if __name__ == "__main__":
    unittest.main()
