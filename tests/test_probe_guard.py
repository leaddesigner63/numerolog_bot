import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app


class ProbeGuardMiddlewareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_blocks_wordpress_probe_path(self) -> None:
        response = self.client.get("/wordpress/wp-admin/setup-config.php")
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["detail"], "Resource not available")


    def test_root_endpoint_available_for_external_probes(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_health_remains_available(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readiness_returns_200_when_database_is_available(self) -> None:
        class FakeSession:
            def execute(self, *_args, **_kwargs) -> None:
                return None

        @contextmanager
        def fake_get_session():
            yield FakeSession()

        with patch("app.api.routes.health.get_session", fake_get_session):
            response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})

    def test_readiness_returns_503_when_database_is_unavailable(self) -> None:
        @contextmanager
        def failing_get_session():
            raise RuntimeError("db timeout")
            yield

        with patch("app.api.routes.health.get_session", failing_get_session):
            response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_ready")
        self.assertIn("database_unavailable", response.json()["reason"])


if __name__ == "__main__":
    unittest.main()
