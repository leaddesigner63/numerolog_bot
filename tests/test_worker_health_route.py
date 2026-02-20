import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import ReportJobStatus
from app.main import create_app


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _SessionStub:
    def __init__(self, heartbeat=None, rows=None):
        self._heartbeat = heartbeat
        self._rows = rows or []

    def get(self, model, key):
        return self._heartbeat

    def execute(self, query):
        return _Result(self._rows)


class WorkerHealthRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_report_worker_health_returns_alive_and_job_counters(self) -> None:
        heartbeat = type("Heartbeat", (), {})()
        heartbeat.updated_at = datetime.now(timezone.utc)
        rows = [
            (ReportJobStatus.PENDING, 4),
            (ReportJobStatus.IN_PROGRESS, 2),
            (ReportJobStatus.FAILED, 1),
        ]

        @contextmanager
        def fake_get_session():
            yield _SessionStub(heartbeat=heartbeat, rows=rows)

        with patch("app.api.routes.worker_health.get_session", fake_get_session):
            response = self.client.get("/health/report-worker")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["alive"])
        self.assertEqual(payload["jobs"]["pending"], 4)
        self.assertEqual(payload["jobs"]["in_progress"], 2)
        self.assertEqual(payload["jobs"]["failed"], 1)
        self.assertIsNotNone(payload["last_seen_at"])

    def test_report_worker_health_heartbeat_fallback(self) -> None:
        @contextmanager
        def fake_get_session_with_heartbeat_error():
            raise SQLAlchemyError("heartbeat_table_missing")
            yield

        with patch(
            "app.api.routes.worker_health.get_session",
            fake_get_session_with_heartbeat_error,
        ):
            response = self.client.get("/health/report-worker")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["alive"])
        self.assertIn("reason", payload)


if __name__ == "__main__":
    unittest.main()
