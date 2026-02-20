import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.handlers import questionnaire


class QuestionnaireCopyCurrentAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_copy_current_answer_uses_ephemeral_message_instead_of_direct_answer(self) -> None:
        callback_message = SimpleNamespace(
            answer=AsyncMock(),
            chat=SimpleNamespace(id=202),
            bot=AsyncMock(),
        )
        callback = SimpleNamespace(
            message=callback_message,
            from_user=SimpleNamespace(id=101),
            answer=AsyncMock(),
        )
        state = AsyncMock()
        state.get_data = AsyncMock(
            return_value={
                "current_question_id": "q1",
                "answers": {"q1": "Мой текущий ответ"},
            }
        )

        with patch.object(
            questionnaire.screen_manager,
            "send_ephemeral_message",
            new=AsyncMock(),
        ) as send_ephemeral_message:
            await questionnaire.copy_current_answer(callback, state)

        send_ephemeral_message.assert_awaited_once_with(
            callback_message,
            "Текущий ответ:\nМой текущий ответ",
            user_id=101,
            delete_delay_seconds=3,
        )
        callback_message.answer.assert_not_awaited()
        callback.answer.assert_awaited_once_with(
            "Ответ отправлен отдельным сообщением.",
            show_alert=False,
        )


if __name__ == "__main__":
    unittest.main()
