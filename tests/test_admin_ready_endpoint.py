import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app


class AdminReadyEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_admin_ready_returns_200_when_database_is_available(self) -> None:
        class FakeSession:
            def execute(self, *_args, **_kwargs) -> None:
                return None

            def close(self) -> None:
                return None

        def fake_factory():
            return FakeSession()

        with patch("app.api.routes.admin.get_session_factory", return_value=fake_factory):
            response = self.client.get("/admin/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")
        self.assertTrue(response.json()["database_ok"])

    def test_admin_ready_returns_503_when_database_is_unavailable(self) -> None:
        def failing_factory():
            raise RuntimeError("db timeout")

        with patch("app.api.routes.admin.get_session_factory", return_value=failing_factory):
            response = self.client.get("/admin/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_ready")
        self.assertFalse(response.json()["database_ok"])
        self.assertIn("admin_database_unavailable", response.json()["reason"])


if __name__ == "__main__":
    unittest.main()
