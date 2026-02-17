import unittest

from app.bot.screens import screen_s4_consent
from app.core.config import settings


class ScreenS4ConsentTests(unittest.TestCase):
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
