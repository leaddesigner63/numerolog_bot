import unittest
from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import User, UserFirstTouchAttribution
from app.services import traffic_attribution as traffic_attribution_module


class TrafficAttributionUserBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

        @contextmanager
        def _test_get_session():
            session = self.SessionLocal()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        self._old_get_session = traffic_attribution_module.get_session
        traffic_attribution_module.get_session = _test_get_session

    def tearDown(self) -> None:
        traffic_attribution_module.get_session = self._old_get_session
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_save_first_touch_creates_user_when_missing(self) -> None:
        saved = traffic_attribution_module.save_user_first_touch_attribution(
            telegram_user_id=777001,
            payload="site_seo_cta",
            telegram_username="seo-user",
        )
        self.assertTrue(saved)

        with self.SessionLocal() as session:
            user = session.execute(select(User).where(User.telegram_user_id == 777001)).scalar_one_or_none()
            record = session.execute(
                select(UserFirstTouchAttribution).where(UserFirstTouchAttribution.telegram_user_id == 777001)
            ).scalar_one_or_none()

        self.assertIsNotNone(user)
        self.assertEqual(user.telegram_username, "seo-user")
        self.assertIsNotNone(record)
        self.assertEqual(record.source, "site")
        self.assertEqual(record.campaign, "seo")
        self.assertEqual(record.placement, "cta")


    def test_parse_first_touch_payload_supports_marker_format_and_preserves_placement(self) -> None:
        parsed = traffic_attribution_module.parse_first_touch_payload("src_sitecmp_launchpl_tariff_t2")
        self.assertEqual(parsed["start_payload"], "src_sitecmp_launchpl_tariff_t2")
        self.assertEqual(parsed["source"], "site")
        self.assertEqual(parsed["campaign"], "launch")
        self.assertEqual(parsed["placement"], "tariff_t2")

    def test_parse_first_touch_payload_supports_underscore_format_with_complex_placement(self) -> None:
        parsed = traffic_attribution_module.parse_first_touch_payload("site_seo_tariff_t3")
        self.assertEqual(parsed["start_payload"], "site_seo_tariff_t3")
        self.assertEqual(parsed["source"], "site")
        self.assertEqual(parsed["campaign"], "seo")
        self.assertEqual(parsed["placement"], "tariff_t3")

    def test_parse_first_touch_payload_supports_tme_links_and_start_prefix(self) -> None:
        parsed_from_link = traffic_attribution_module.parse_first_touch_payload(
            "https://t.me/AIreadUbot?start=site_seo_cta"
        )
        self.assertEqual(parsed_from_link["start_payload"], "site_seo_cta")
        self.assertEqual(parsed_from_link["source"], "site")
        self.assertEqual(parsed_from_link["campaign"], "seo")
        self.assertEqual(parsed_from_link["placement"], "cta")

        parsed_from_prefix = traffic_attribution_module.parse_first_touch_payload("start=site_seo_cta")
        self.assertEqual(parsed_from_prefix["start_payload"], "site_seo_cta")
        self.assertEqual(parsed_from_prefix["source"], "site")
        self.assertEqual(parsed_from_prefix["campaign"], "seo")
        self.assertEqual(parsed_from_prefix["placement"], "cta")


if __name__ == "__main__":
    unittest.main()
