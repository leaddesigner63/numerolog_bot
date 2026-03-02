import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.handlers.screens import _send_feedback_to_admins


class FeedbackMediaDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_feedback_photo_to_admin_and_group(self) -> None:
        bot = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock(), send_document=AsyncMock())
        with patch("app.bot.handlers.screens.settings") as settings:
            settings.admin_ids = "10,11"
            settings.feedback_group_chat_id = -100777
            delivered = await _send_feedback_to_admins(
                bot,
                feedback_text="",
                user_id=55,
                username="alice",
                attachment_type="photo",
                attachment_file_id="ph_123",
                attachment_caption="оплата",
                order_id=987,
                tariff="T2",
                amount=2190,
            )

        self.assertTrue(delivered)
        self.assertEqual(bot.send_photo.await_count, 3)
        bot.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
