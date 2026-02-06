from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class LLMKeyItem:
    key: str
    db_id: int | None = None
    provider: str | None = None


def parse_env_keys(primary_key: str | None, extra_keys: str | None) -> list[LLMKeyItem]:
    keys: list[LLMKeyItem] = []
    if primary_key and primary_key.strip():
        keys.append(LLMKeyItem(key=primary_key.strip()))
    if extra_keys and extra_keys.strip():
        for part in extra_keys.split(","):
            value = part.strip()
            if value:
                keys.append(LLMKeyItem(key=value))
    return keys


def load_db_keys(provider: str) -> list[LLMKeyItem]:
    try:
        from app.db.models import LLMApiKey
        from app.db.session import get_session_factory
        from sqlalchemy import select
    except Exception:
        return []

    try:
        session_factory = get_session_factory()
        session = session_factory()
    except Exception:
        return []

    try:
        rows = session.execute(
            select(LLMApiKey)
            .where(LLMApiKey.provider == provider, LLMApiKey.is_active.is_(True))
            .order_by(LLMApiKey.priority.asc(), LLMApiKey.created_at.asc())
        ).scalars()
        return [
            LLMKeyItem(key=row.key, db_id=row.id, provider=row.provider) for row in rows
        ]
    except Exception:
        return []
    finally:
        session.close()


def resolve_llm_keys(
    *,
    provider: str,
    primary_key: str | None,
    extra_keys: str | None,
) -> list[LLMKeyItem]:
    db_keys = load_db_keys(provider)
    if db_keys:
        return db_keys
    return parse_env_keys(primary_key, extra_keys)


def record_llm_key_usage(
    key_item: LLMKeyItem,
    *,
    success: bool,
    status_code: int | None = None,
    error_message: str | None = None,
) -> None:
    if not key_item.db_id:
        return

    try:
        from app.db.models import LLMApiKey
        from app.db.session import get_session_factory
    except Exception:
        return

    try:
        session_factory = get_session_factory()
        session = session_factory()
    except Exception:
        return

    try:
        record = session.get(LLMApiKey, key_item.db_id)
        if not record:
            session.close()
            return
        now = datetime.now(timezone.utc)
        record.last_used_at = now
        record.last_status_code = status_code
        if success:
            record.last_success_at = now
            record.last_error = None
            record.success_count = (record.success_count or 0) + 1
        else:
            record.last_error = error_message
            record.failure_count = (record.failure_count or 0) + 1
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()
