#!/usr/bin/env python3
"""One-off backfill metadata.tariff в screen_transition_events.

Восстановление выполняется по приоритету:
1) tariff в metadata (если уже задано, событие пропускается);
2) trigger_value формата tariff:T*;
3) ближайший известный тариф того же пользователя (соседние события по времени/id).
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import ScreenTransitionEvent
from app.services.admin_analytics import _extract_tariff_from_trigger_value

_ALLOWED_TARIFFS = {"T0", "T1", "T2", "T3"}


def _resolve_database_url(cli_value: str | None) -> str | None:
    return cli_value or os.getenv("DATABASE_URL")


def _event_metadata(event: ScreenTransitionEvent) -> dict:
    if isinstance(event.metadata_json, dict):
        return dict(event.metadata_json)
    return {}


def _has_tariff(event: ScreenTransitionEvent) -> bool:
    metadata = _event_metadata(event)
    return str(metadata.get("tariff") or "").strip().upper() in _ALLOWED_TARIFFS


def _run_backfill(session: Session, dry_run: bool) -> tuple[int, int]:
    rows = session.execute(
        select(ScreenTransitionEvent).order_by(
            ScreenTransitionEvent.telegram_user_id.asc(),
            ScreenTransitionEvent.created_at.asc(),
            ScreenTransitionEvent.id.asc(),
        )
    ).scalars().all()

    known_tariff_by_user: dict[int, str] = {}
    unresolved_by_user: dict[int, list[ScreenTransitionEvent]] = defaultdict(list)
    updated = 0

    for event in rows:
        user_id = int(event.telegram_user_id or 0)
        metadata = _event_metadata(event)
        metadata_tariff = str(metadata.get("tariff") or "").strip().upper()
        if metadata_tariff in _ALLOWED_TARIFFS:
            known_tariff_by_user[user_id] = metadata_tariff
            continue

        trigger_tariff = _extract_tariff_from_trigger_value(event.trigger_value)
        if trigger_tariff in _ALLOWED_TARIFFS:
            metadata["tariff"] = trigger_tariff
            event.metadata_json = metadata
            known_tariff_by_user[user_id] = trigger_tariff
            updated += 1
            continue

        if known_tariff_by_user.get(user_id):
            metadata["tariff"] = known_tariff_by_user[user_id]
            event.metadata_json = metadata
            updated += 1
            continue

        unresolved_by_user[user_id].append(event)

    for user_id, pending_events in unresolved_by_user.items():
        fallback_tariff = known_tariff_by_user.get(user_id)
        if not fallback_tariff:
            continue
        for event in pending_events:
            if _has_tariff(event):
                continue
            metadata = _event_metadata(event)
            metadata["tariff"] = fallback_tariff
            event.metadata_json = metadata
            updated += 1

    if dry_run:
        session.rollback()
    else:
        session.commit()

    return updated, len(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    database_url = _resolve_database_url(args.database_url)
    if not database_url:
        print("DATABASE_URL не задан. Передайте --database-url или переменную окружения DATABASE_URL.")
        return 1

    engine = create_engine(database_url)
    with Session(engine) as session:
        updated, total = _run_backfill(session, args.dry_run)

    mode = "DRY RUN" if args.dry_run else "APPLIED"
    print(f"{mode}: обработано событий={total}, обновлено metadata.tariff={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
