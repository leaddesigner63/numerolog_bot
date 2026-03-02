import unittest
from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import User, UserFirstTouchAttribution, UserTouchEvent
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
            touch_events = session.execute(
                select(UserTouchEvent).where(UserTouchEvent.telegram_user_id == 777001)
            ).scalars().all()

        self.assertIsNotNone(user)
        self.assertEqual(user.telegram_username, "seo-user")
        self.assertIsNotNone(record)
        self.assertEqual(record.source, "site")
        self.assertEqual(record.campaign, "seo")
        self.assertEqual(record.placement, "cta")
        self.assertEqual(len(touch_events), 1)
        self.assertEqual(touch_events[0].source, "site")

    def test_repeated_payload_creates_touch_events_but_preserves_single_first_touch(self) -> None:
        first_saved = traffic_attribution_module.save_user_first_touch_attribution(
            telegram_user_id=777002,
            payload="site_cmp_one",
        )
        second_saved = traffic_attribution_module.save_user_first_touch_attribution(
            telegram_user_id=777002,
            payload="site_cmp_two",
        )

        self.assertTrue(first_saved)
        self.assertFalse(second_saved)

        with self.SessionLocal() as session:
            first_touch_records = session.execute(
                select(UserFirstTouchAttribution).where(UserFirstTouchAttribution.telegram_user_id == 777002)
            ).scalars().all()
            touch_events = session.execute(
                select(UserTouchEvent).where(UserTouchEvent.telegram_user_id == 777002)
            ).scalars().all()

        self.assertEqual(len(first_touch_records), 1)
        self.assertEqual(len(touch_events), 2)

    def test_empty_start_then_payload_creates_touch_event_on_first_call(self) -> None:
        first_saved = traffic_attribution_module.save_user_first_touch_attribution(
            telegram_user_id=777003,
            payload=None,
        )
        second_saved = traffic_attribution_module.save_user_first_touch_attribution(
            telegram_user_id=777003,
            payload="site_seo_cta",
        )

        self.assertFalse(first_saved)
        self.assertTrue(second_saved)

        with self.SessionLocal() as session:
            first_touch_records = session.execute(
                select(UserFirstTouchAttribution).where(UserFirstTouchAttribution.telegram_user_id == 777003)
            ).scalars().all()
            touch_events = session.execute(
                select(UserTouchEvent).where(UserTouchEvent.telegram_user_id == 777003)
            ).scalars().all()

        self.assertEqual(len(first_touch_records), 1)
        self.assertEqual(first_touch_records[0].start_payload, "site_seo_cta")
        self.assertEqual(first_touch_records[0].source, "site")
        self.assertEqual(first_touch_records[0].campaign, "seo")
        self.assertEqual(first_touch_records[0].placement, "cta")
        self.assertEqual(len(touch_events), 2)
        self.assertEqual(touch_events[0].start_payload, "")
        self.assertIsNone(touch_events[0].source)
        self.assertIsNone(touch_events[0].campaign)
        self.assertIsNone(touch_events[0].placement)
        self.assertEqual(touch_events[1].start_payload, "site_seo_cta")

    def test_existing_empty_first_touch_can_be_updated_once(self) -> None:
        with self.SessionLocal() as session:
            session.add(
                UserFirstTouchAttribution(
                    telegram_user_id=777004,
                    start_payload="",
                    source=None,
                    campaign=None,
                    placement=None,
                    raw_parts=None,
                )
            )
            session.commit()

        first_saved = traffic_attribution_module.save_user_first_touch_attribution(
            telegram_user_id=777004,
            payload="site_seo_cta",
        )
        second_saved = traffic_attribution_module.save_user_first_touch_attribution(
            telegram_user_id=777004,
            payload="site_other_cta2",
        )

        self.assertTrue(first_saved)
        self.assertFalse(second_saved)

        with self.SessionLocal() as session:
            first_touch_record = session.execute(
                select(UserFirstTouchAttribution).where(UserFirstTouchAttribution.telegram_user_id == 777004)
            ).scalar_one()

        self.assertEqual(first_touch_record.start_payload, "site_seo_cta")
        self.assertEqual(first_touch_record.source, "site")
        self.assertEqual(first_touch_record.campaign, "seo")
        self.assertEqual(first_touch_record.placement, "cta")

    def test_parse_first_touch_payload_supports_exact_querystring_format(self) -> None:
        parsed = traffic_attribution_module.parse_first_touch_payload(
            "src=site.ads_v2&cmp=cmp_launch.pl_1&pl=cta_cmp_main_pl_footer"
        )
        self.assertEqual(parsed["start_payload"], "src=site.ads_v2&cmp=cmp_launch.pl_1&pl=cta_cmp_main_pl_footer")
        self.assertEqual(parsed["source"], "site.ads_v2")
        self.assertEqual(parsed["campaign"], "cmp_launch.pl_1")
        self.assertEqual(parsed["placement"], "cta_cmp_main_pl_footer")

    def test_parse_first_touch_payload_supports_urlencoded_querystring_payload(self) -> None:
        parsed = traffic_attribution_module.parse_first_touch_payload(
            "src%3Dsite.ads_v2%26cmp%3Dcmp_launch.pl_1%26pl%3Dcta_cmp_main_pl_footer"
        )
        self.assertEqual(parsed["start_payload"], "src=site.ads_v2&cmp=cmp_launch.pl_1&pl=cta_cmp_main_pl_footer")
        self.assertEqual(parsed["source"], "site.ads_v2")
        self.assertEqual(parsed["campaign"], "cmp_launch.pl_1")
        self.assertEqual(parsed["placement"], "cta_cmp_main_pl_footer")

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
            "https://t.me/AIreadUbot?start=src%3Dsite%26cmp%3Dseo%26pl%3Dcta"
        )
        self.assertEqual(parsed_from_link["start_payload"], "src=site&cmp=seo&pl=cta")
        self.assertEqual(parsed_from_link["source"], "site")
        self.assertEqual(parsed_from_link["campaign"], "seo")
        self.assertEqual(parsed_from_link["placement"], "cta")

        parsed_from_prefix = traffic_attribution_module.parse_first_touch_payload("start=src%3Dsite%26cmp%3Dseo%26pl%3Dcta")
        self.assertEqual(parsed_from_prefix["start_payload"], "src=site&cmp=seo&pl=cta")
        self.assertEqual(parsed_from_prefix["source"], "site")
        self.assertEqual(parsed_from_prefix["campaign"], "seo")
        self.assertEqual(parsed_from_prefix["placement"], "cta")


if __name__ == "__main__":
    unittest.main()
