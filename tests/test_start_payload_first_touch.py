import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.handlers import screen_manager as screen_manager_module
from app.bot.handlers import start as start_module
from app.bot.handlers.screen_manager import screen_manager
from app.db.base import Base
from app.db.models import User, UserFirstTouchAttribution
from app.services import traffic_attribution as traffic_attribution_module


class StartPayloadFirstTouchTests(unittest.IsolatedAsyncioTestCase):
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

        self._old_get_session = start_module.get_session
        self._old_screen_manager_get_session = screen_manager_module.get_session
        self._old_traffic_get_session = traffic_attribution_module.get_session
        start_module.get_session = _test_get_session
        screen_manager_module.get_session = _test_get_session
        traffic_attribution_module.get_session = _test_get_session
        screen_manager._store._states.clear()

        with self.SessionLocal() as session:
            session.add(User(id=1, telegram_user_id=123456, telegram_username="first-touch"))
            session.commit()

    def tearDown(self) -> None:
        start_module.get_session = self._old_get_session
        screen_manager_module.get_session = self._old_screen_manager_get_session
        traffic_attribution_module.get_session = self._old_traffic_get_session
        screen_manager._store._states.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _message(self, text: str):
        return SimpleNamespace(
            text=text,
            bot=SimpleNamespace(),
            chat=SimpleNamespace(id=9001),
            from_user=SimpleNamespace(id=123456),
        )

    def _first_touch_records(self) -> list[UserFirstTouchAttribution]:
        with self.SessionLocal() as session:
            return list(
                session.query(UserFirstTouchAttribution)
                .filter(UserFirstTouchAttribution.telegram_user_id == 123456)
                .all()
            )

    async def test_start_payload_persists_only_first_touch_payload(self) -> None:
        with patch.object(screen_manager, "show_screen", new=AsyncMock()):
            await start_module.handle_start(self._message("/start source_a_campaign_a"))
            await start_module.handle_start(self._message("/start source_b_campaign_b"))

        records = self._first_touch_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].start_payload, "source_a_campaign_a")
        self.assertEqual(records[0].source, "source")
        self.assertEqual(records[0].campaign, "a")


if __name__ == "__main__":
    unittest.main()
