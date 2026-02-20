import unittest
from unittest.mock import AsyncMock, patch

from app.bot.handlers.screen_manager import ScreenManager, ScreenState


class TextInputModeHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_enter_text_input_mode_deletes_last_question_by_default(self) -> None:
        manager = ScreenManager()
        bot = AsyncMock()

        with patch.object(manager, "delete_last_question_message", new=AsyncMock()) as delete_last, patch.object(
            manager,
            "clear_current_screen_inline_keyboards",
            new=AsyncMock(),
        ) as clear_inline:
            await manager.enter_text_input_mode(bot=bot, chat_id=101, user_id=7)

        delete_last.assert_awaited_once_with(bot=bot, chat_id=101, user_id=7)
        clear_inline.assert_awaited_once_with(
            bot=bot,
            chat_id=101,
            user_id=7,
            cleanup_mode="remove_keyboard_only",
        )

    async def test_enter_text_input_mode_preserve_last_question(self) -> None:
        manager = ScreenManager()
        bot = AsyncMock()

        with patch.object(manager, "delete_last_question_message", new=AsyncMock()) as delete_last, patch.object(
            manager,
            "clear_current_screen_inline_keyboards",
            new=AsyncMock(),
        ) as clear_inline:
            await manager.enter_text_input_mode(
                bot=bot,
                chat_id=101,
                user_id=7,
                preserve_last_question=True,
            )

        delete_last.assert_not_awaited()
        clear_inline.assert_awaited_once_with(
            bot=bot,
            chat_id=101,
            user_id=7,
            cleanup_mode="remove_keyboard_only",
        )

    async def test_enter_text_input_mode_delete_messages_mode(self) -> None:
        manager = ScreenManager()
        bot = AsyncMock()

        with patch.object(manager, "delete_last_question_message", new=AsyncMock()) as delete_last, patch.object(
            manager,
            "clear_current_screen_inline_keyboards",
            new=AsyncMock(),
        ) as clear_inline:
            await manager.enter_text_input_mode(
                bot=bot,
                chat_id=101,
                user_id=7,
                cleanup_mode="delete_messages",
            )

        delete_last.assert_awaited_once_with(bot=bot, chat_id=101, user_id=7)
        clear_inline.assert_awaited_once_with(
            bot=bot,
            chat_id=101,
            user_id=7,
            cleanup_mode="delete_messages",
        )

    async def test_clear_current_screen_inline_keyboards_remove_keyboard_only(self) -> None:
        manager = ScreenManager()
        bot = AsyncMock()
        manager._store._persist_state = lambda *_args, **_kwargs: None

        manager._store._states[7] = ScreenState(screen_id="S4", message_ids=[11, 12])

        await manager.clear_current_screen_inline_keyboards(
            bot=bot,
            chat_id=101,
            user_id=7,
            cleanup_mode="remove_keyboard_only",
        )

        self.assertEqual(bot.edit_message_reply_markup.await_count, 2)
        bot.delete_message.assert_not_awaited()
        state = manager.get_state(7)
        self.assertEqual(state.message_ids, [11, 12])

    async def test_clear_current_screen_inline_keyboards_delete_messages(self) -> None:
        manager = ScreenManager()
        bot = AsyncMock()
        manager._store._persist_state = lambda *_args, **_kwargs: None

        manager._store._states[7] = ScreenState(screen_id="S4", message_ids=[11, 12])
        manager.add_user_message_id(7, 21)

        await manager.clear_current_screen_inline_keyboards(
            bot=bot,
            chat_id=101,
            user_id=7,
            cleanup_mode="delete_messages",
        )

        self.assertEqual(bot.delete_message.await_count, 3)
        bot.edit_message_reply_markup.assert_not_awaited()
        state = manager.get_state(7)
        self.assertEqual(state.message_ids, [])
        self.assertEqual(state.user_message_ids, [])


if __name__ == "__main__":
    unittest.main()
