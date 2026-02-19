import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.handlers import questionnaire


class QuestionnaireLkAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_edit_from_lk_does_not_check_paid_order(self) -> None:
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=101, username="tester"),
            message=SimpleNamespace(chat=SimpleNamespace(id=202), bot=AsyncMock()),
            bot=AsyncMock(),
            answer=AsyncMock(),
        )
        state = AsyncMock()
        ensure_paid_access = AsyncMock(return_value=False)

        with (
            patch.object(questionnaire, "_ensure_questionnaire_access", new=ensure_paid_access),
            patch.object(questionnaire, "_ensure_profile_ready", new=AsyncMock(return_value=True)),
            patch.object(questionnaire, "_start_edit_questionnaire", new=AsyncMock()) as start_edit,
        ):
            await questionnaire.edit_questionnaire_from_lk(callback, state)

        ensure_paid_access.assert_not_awaited()
        start_edit.assert_awaited_once()
        callback.answer.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
