import hashlib
import unittest

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app


class AdminPromptDangerZoneUITests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_login = settings.admin_login
        self.previous_password = settings.admin_password
        settings.admin_login = "admin"
        settings.admin_password = "secret"
        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        settings.admin_login = self.previous_login
        settings.admin_password = self.previous_password

    def test_admin_ui_contains_prompt_danger_zone_section(self) -> None:
        token = hashlib.sha256(b"admin:secret").hexdigest()
        response = self.client.get("/admin", cookies={"admin_session": token})

        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("id=\"promptDangerZone\"", html)
        self.assertIn("detectPromptDangerZones", html)
        self.assertIn("renderPromptDangerZones", html)
        self.assertIn("promptDangerRules", html)
        self.assertIn("raw-angle-brackets", html)
        self.assertIn("html-entities", html)
        self.assertIn(r"pattern: /<[^\n>]*>|<|>/g", html)
        self.assertIn('content[idx] === "\\n"', html)
        self.assertNotIn("replaceAll(", html)
        self.assertNotIn("matchAll(", html)


if __name__ == "__main__":
    unittest.main()
