from contextlib import contextmanager
import logging
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def get_engine() -> Engine:
    if not settings.database_url:
        logger = logging.getLogger(__name__)
        logger.warning("database_url_missing_fallback_to_sqlite")
        storage_dir = Path("storage")
        storage_dir.mkdir(parents=True, exist_ok=True)
        sqlite_url = f"sqlite:///{(storage_dir / 'numerolog_bot.sqlite3').resolve()}"
        return create_engine(sqlite_url, connect_args={"check_same_thread": False})
    return create_engine(settings.database_url, pool_pre_ping=True)


def get_session_factory() -> sessionmaker[Session]:
    engine = get_engine()
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@contextmanager
def get_session() -> Session:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
