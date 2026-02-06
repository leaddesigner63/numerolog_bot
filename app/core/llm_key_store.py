from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging


@dataclass(frozen=True)
class LLMKeyItem:
    key: str
    db_id: int | None = None
    provider: str | None = None


logger = logging.getLogger(__name__)


def _filter_key_items(items: list[LLMKeyItem]) -> list[LLMKeyItem]:
    filtered: list[LLMKeyItem] = []
    for item in items:
        if item.key is None:
            continue
        key_value = item.key
        if isinstance(key_value, str) and not key_value.strip():
            continue
        filtered.append(item)
    return filtered


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
        from sqlalchemy import func, select
    except Exception:
        logger.warning("llm_key_store_db_import_failed")
        return []

    try:
        session_factory = get_session_factory()
        session = session_factory()
    except Exception:
        logger.warning("llm_key_store_session_failed")
        return []

    try:
        rows = session.execute(
            select(LLMApiKey)
            .where(
                func.lower(func.trim(LLMApiKey.provider)) == func.lower(func.trim(provider)),
                LLMApiKey.is_active.is_(True),
            )
            .order_by(LLMApiKey.priority.asc(), LLMApiKey.created_at.asc())
        ).scalars()
        return [
            LLMKeyItem(key=row.key, db_id=row.id, provider=row.provider) for row in rows
        ]
    except Exception:
        logger.warning("llm_key_store_query_failed")
        return []
    finally:
        session.close()


def ensure_env_keys_in_db(
    *,
    provider: str,
    primary_key: str | None,
    extra_keys: str | None,
) -> list[LLMKeyItem]:
    env_keys = parse_env_keys(primary_key, extra_keys)
    if not env_keys:
        return []

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
        existing = session.execute(
            select(LLMApiKey).where(LLMApiKey.provider == provider)
        ).scalars()
        existing_map = {record.key: record for record in existing}
        created_or_updated: list[LLMApiKey] = []
        for index, key_item in enumerate(env_keys, start=1):
            record = existing_map.get(key_item.key)
            if record:
                record.is_active = True
                record.priority = str(index * 10)
                created_or_updated.append(record)
                continue
            record = LLMApiKey(
                provider=provider,
                key=key_item.key,
                is_active=True,
                priority=str(index * 10),
            )
            session.add(record)
            created_or_updated.append(record)

        if created_or_updated:
            session.commit()

        refreshed = session.execute(
            select(LLMApiKey)
            .where(LLMApiKey.provider == provider, LLMApiKey.is_active.is_(True))
            .order_by(LLMApiKey.priority.asc(), LLMApiKey.created_at.asc())
        ).scalars()
        return [
            LLMKeyItem(key=row.key, db_id=row.id, provider=row.provider) for row in refreshed
        ]
    except Exception:
        session.rollback()
        return []
    finally:
        session.close()


def resolve_llm_keys(
    *,
    provider: str,
    primary_key: str | None,
    extra_keys: str | None,
) -> list[LLMKeyItem]:
    db_keys = _filter_key_items(load_db_keys(provider))
    if db_keys:
        env_keys = _filter_key_items(parse_env_keys(primary_key, extra_keys))
        if env_keys:
            return db_keys + env_keys
        return db_keys
    synced_keys = ensure_env_keys_in_db(
        provider=provider,
        primary_key=primary_key,
        extra_keys=extra_keys,
    )
    synced_keys = _filter_key_items(synced_keys)
    if synced_keys:
        return synced_keys
    return _filter_key_items(parse_env_keys(primary_key, extra_keys))


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
