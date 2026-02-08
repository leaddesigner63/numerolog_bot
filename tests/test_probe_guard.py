import unittest

from fastapi.testclient import TestClient

from app.main import create_app


class ProbeGuardMiddlewareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_blocks_wordpress_probe_path(self) -> None:
        response = self.client.get("/wordpress/wp-admin/setup-config.php")
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["detail"], "Resource not available")

    def test_health_remains_available(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
