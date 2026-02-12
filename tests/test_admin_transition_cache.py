import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.api.routes import admin
from app.services.admin_analytics import AnalyticsFilters


class TransitionAnalyticsCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        admin._transition_analytics_cache.clear()

    def test_returns_cached_value_within_ttl(self) -> None:
        filters = AnalyticsFilters(from_dt=datetime(2026, 1, 1, tzinfo=timezone.utc), limit=100)
        session = object()

        with patch("app.api.routes.admin._safe_build_transition_analytics", return_value={"summary": {"events": 1}}) as build:
            first = admin._get_transition_analytics(session, filters)
            second = admin._get_transition_analytics(session, filters)

        self.assertEqual(first, second)
        self.assertEqual(build.call_count, 1)

    def test_refreshes_value_after_ttl_expired(self) -> None:
        filters = AnalyticsFilters(limit=10)
        session = object()
        cache_key = admin._transition_analytics_cache_key(filters)
        admin._transition_analytics_cache[cache_key] = (100.0, {"summary": {"events": 1}})

        with (
            patch("app.api.routes.admin._safe_build_transition_analytics", return_value={"summary": {"events": 2}}) as build,
            patch("app.api.routes.admin.time.monotonic", return_value=106.1),
        ):
            result = admin._get_transition_analytics(session, filters)

        self.assertEqual(build.call_count, 1)
        self.assertEqual(result["summary"]["events"], 2)


if __name__ == "__main__":
    unittest.main()
