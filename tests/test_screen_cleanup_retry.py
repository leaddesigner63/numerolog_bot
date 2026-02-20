import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from aiogram.exceptions import TelegramBadRequest

from app.bot.handlers.screen_manager import ScreenContent, ScreenManager, ScreenState


class InMemoryScreenStateStore:
    def __init__(self) -> None:
        self.state = ScreenState()

    def get_state(self, user_id: int) -> ScreenState:
        return self.state

    def pop_pdf_message_ids(self, user_id: int) -> list[int]:
        return []

    def clear_message_ids(self, user_id: int) -> None:
        self.state.message_ids = []

    def clear_user_message_ids(self, user_id: int) -> None:
        self.state.user_message_ids = []

    def remove_user_message_id(self, user_id: int, message_id: int) -> ScreenState:
        self.state.user_message_ids = [
            mid for mid in self.state.user_message_ids if mid != message_id
        ]
        return self.state

    def clear_last_question_message_id(self, user_id: int) -> None:
        self.state.last_question_message_id = None

    def update_screen(
        self, user_id: int, screen_id: str, message_ids: list[int]
    ) -> ScreenState:
        self.state.screen_id = screen_id
        self.state.message_ids = list(message_ids)
        return self.state

    def update_data(self, user_id: int, **kwargs: object) -> ScreenState:
        self.state.data.update(kwargs)
        return self.state

    def add_screen_message_id(self, user_id: int, message_id: int) -> ScreenState:
        self.state.message_ids.append(message_id)
        return self.state


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

    async def test_user_message_cleanup_retry_success_clears_state(self) -> None:
        store = InMemoryScreenStateStore()
        store.state.user_message_ids = [21]
        manager = ScreenManager(store=store)
        manager.render_screen = lambda *_args, **_kwargs: ScreenContent(messages=["ok"])
        manager._send_message_with_fallback = AsyncMock(
            return_value=SimpleNamespace(message_id=99)
        )
        manager._record_transition_event = lambda **_kwargs: None
        manager._record_funnel_events = lambda **_kwargs: None
        manager._logger.warning = Mock()

        bot = AsyncMock()

        async def delete_side_effect(*, chat_id: int, message_id: int) -> None:
            if message_id == 21 and not hasattr(delete_side_effect, "attempted"):
                delete_side_effect.attempted = True
                raise TelegramBadRequest(
                    method="deleteMessage",
                    message="Bad Request: message can't be deleted",
                )

        bot.delete_message.side_effect = delete_side_effect

        result = await manager.show_screen(bot, chat_id=1, user_id=1, screen_id="S1")

        self.assertTrue(result)
        self.assertEqual(store.state.user_message_ids, [])

    async def test_user_message_cleanup_full_failure_keeps_state(self) -> None:
        store = InMemoryScreenStateStore()
        store.state.user_message_ids = [33]
        manager = ScreenManager(store=store)
        manager.render_screen = lambda *_args, **_kwargs: ScreenContent(messages=["ok"])
        manager._send_message_with_fallback = AsyncMock(
            return_value=SimpleNamespace(message_id=99)
        )
        manager._record_transition_event = lambda **_kwargs: None
        manager._record_funnel_events = lambda **_kwargs: None
        manager._logger.warning = Mock()

        bot = AsyncMock()
        bot.delete_message.side_effect = TelegramBadRequest(
            method="deleteMessage",
            message="Bad Request: message can't be deleted",
        )

        result = await manager.show_screen(bot, chat_id=1, user_id=1, screen_id="S1")

        self.assertTrue(result)
        self.assertEqual(store.state.user_message_ids, [33])
        self.assertGreaterEqual(manager._logger.warning.call_count, 1)


if __name__ == "__main__":
    unittest.main()
