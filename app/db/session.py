from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.core.config import settings


def get_engine() -> Engine:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return create_engine(settings.database_url, pool_pre_ping=True)
