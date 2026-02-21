import unittest
from unittest.mock import patch

from app.api.routes import admin
from app.services.admin_analytics import FinanceAnalyticsFilters, MarketingAnalyticsFilters, TrafficAnalyticsFilters


class AdminAnalyticsCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        admin._finance_analytics_cache.clear()
        admin._traffic_analytics_cache.clear()
        admin._marketing_analytics_cache.clear()

    def test_finance_cache_reuses_recent_result(self) -> None:
        filters = FinanceAnalyticsFilters(tariff="T2")
        session = object()

        with patch("app.api.routes.admin._safe_build_finance_analytics", return_value={"summary": {"orders": 1}}) as build:
            first = admin._get_finance_analytics(session, filters)
            second = admin._get_finance_analytics(session, filters)

        self.assertEqual(first, second)
        self.assertEqual(build.call_count, 1)

    def test_traffic_cache_reuses_recent_result(self) -> None:
        filters = TrafficAnalyticsFilters(tariff="T1")
        session = object()

        with patch(
            "app.api.routes.admin._safe_build_traffic_analytics",
            return_value=({"users_started_total": 10}, []),
        ) as build:
            first = admin._get_traffic_analytics(session, filters)
            second = admin._get_traffic_analytics(session, filters)

        self.assertEqual(first, second)
        self.assertEqual(build.call_count, 1)

    def test_marketing_cache_reuses_recent_result(self) -> None:
        filters = MarketingAnalyticsFilters()
        session = object()

        with patch(
            "app.api.routes.admin._safe_build_marketing_subscription_analytics",
            return_value={"summary": {"subscribed": 7}},
        ) as build:
            first = admin._get_marketing_subscription_analytics(session, filters)
            second = admin._get_marketing_subscription_analytics(session, filters)

        self.assertEqual(first, second)
        self.assertEqual(build.call_count, 1)


if __name__ == "__main__":
    unittest.main()
