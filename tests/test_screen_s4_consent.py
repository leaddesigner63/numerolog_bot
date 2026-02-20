import unittest
import re

from app.bot.screens import screen_s4_consent
from app.core.config import settings


class ScreenS4ConsentTests(unittest.TestCase):
    def test_contains_consent_text_and_markdown_link(self) -> None:
        content = screen_s4_consent({})
        message = content.messages[0]

        self.assertIn("Продолжая вы соглашаетесь с", message)
        link_match = re.search(r"\[условиями\]\(([^)]+)\)", message)
        self.assertIsNotNone(link_match)
        newsletter_link_match = re.search(r"\[согласие на получение уведомлений\]\(([^)]+)\)", message)
        self.assertIsNotNone(newsletter_link_match)
        self.assertIn("newsletter-consent", message)

    def test_contains_opt_out_button(self) -> None:
        content = screen_s4_consent({})
        callback_data = [
            button.callback_data
            for row in content.keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]

        self.assertIn("profile:consent:accept_without_marketing", callback_data)

    def test_uses_default_consent_url_when_env_is_empty(self) -> None:
        original = settings.legal_consent_url
        settings.legal_consent_url = None
        try:
            content = screen_s4_consent({})
        finally:
            settings.legal_consent_url = original

        self.assertIn("https://aireadu.ru/legal/consent/", content.messages[0])

    def test_uses_legal_consent_url_from_settings(self) -> None:
        original = settings.legal_consent_url
        settings.legal_consent_url = "https://example.org/legal/consent"
        try:
            content = screen_s4_consent({})
        finally:
            settings.legal_consent_url = original

        self.assertIn("https://example.org/legal/consent", content.messages[0])


if __name__ == "__main__":
    unittest.main()
