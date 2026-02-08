from contextlib import contextmanager
from functools import lru_cache
import logging

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    if not settings.database_url:
        logger = logging.getLogger(__name__)
        logger.error("database_url_missing")
        raise RuntimeError(
            "DATABASE_URL is not configured. Set DATABASE_URL to a PostgreSQL DSN before startup."
        )
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=max(1, settings.database_pool_size),
        max_overflow=max(0, settings.database_max_overflow),
        pool_timeout=max(1, settings.database_pool_timeout_seconds),
        pool_recycle=max(1, settings.database_pool_recycle_seconds),
    )


@lru_cache(maxsize=1)
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
