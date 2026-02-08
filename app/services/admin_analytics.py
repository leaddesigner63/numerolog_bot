from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.models import ScreenTransitionEvent, ScreenTransitionTriggerType


_UNKNOWN_SCREEN = "UNKNOWN"
_SCREEN_ID_PATTERN = re.compile(r"^S\d+(?:_T[0-3])?$")
_FUNNEL_STEPS: list[tuple[str, set[str]]] = [
    ("S0", {"S0"}),
    ("S1", {"S1"}),
    ("S3", {"S3"}),
    ("S5", {"S5"}),
    ("S6_OR_S7", {"S6", "S7"}),
]


@dataclass(frozen=True)
class AnalyticsFilters:
    from_dt: datetime | None = None
    to_dt: datetime | None = None
    tariff: str | None = None
    trigger_type: str | None = None
    unique_users_only: bool = False
    dropoff_window_minutes: int = 60
    limit: int | None = None
    screen_ids: frozenset[str] | None = None


@dataclass(frozen=True)
class EventPoint:
    id: int
    user_id: int
    from_screen: str
    to_screen: str
    trigger_type: str
    tariff: str | None
    created_at: datetime


def build_screen_transition_analytics(session: Session, filters: AnalyticsFilters) -> dict:
    events = _load_events(session, filters)
    if not events:
        return {
            "summary": {"events": 0, "users": 0},
            "transition_matrix": [],
            "funnel": [],
            "dropoff": [],
            "transition_durations": [],
        }

    events_by_user = _group_events_by_user(events)
    return {
        "summary": {
            "events": len(events),
            "users": len(events_by_user),
        },
        "transition_matrix": _build_transition_matrix(events, filters.unique_users_only),
        "funnel": _build_funnel(events_by_user),
        "dropoff": _build_dropoff(events_by_user, filters),
        "transition_durations": _build_transition_durations(events_by_user),
    }


def _load_events(session: Session, filters: AnalyticsFilters) -> list[EventPoint]:
    query: Select[tuple[ScreenTransitionEvent]] = select(ScreenTransitionEvent)
    if filters.from_dt:
        query = query.where(ScreenTransitionEvent.created_at >= filters.from_dt)
    if filters.to_dt:
        query = query.where(ScreenTransitionEvent.created_at <= filters.to_dt)
    if filters.trigger_type:
        query = query.where(ScreenTransitionEvent.trigger_type == filters.trigger_type)

    query = query.order_by(
        ScreenTransitionEvent.telegram_user_id.asc(),
        ScreenTransitionEvent.created_at.asc(),
        ScreenTransitionEvent.id.asc(),
    )
    if filters.limit and filters.limit > 0:
        query = query.limit(filters.limit)
    rows = session.execute(query).scalars().all()

    tariff_filter = filters.tariff.upper() if filters.tariff else None
    events: list[EventPoint] = []
    screen_filter = filters.screen_ids
    for row in rows:
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        tariff_value = metadata.get("tariff")
        if tariff_filter and str(tariff_value or "").upper() != tariff_filter:
            continue
        from_screen = _normalize_screen_id(row.from_screen_id)
        to_screen = _normalize_screen_id(row.to_screen_id)
        if screen_filter and from_screen not in screen_filter and to_screen not in screen_filter:
            continue
        created_at = row.created_at or datetime.now(timezone.utc)
        events.append(
            EventPoint(
                id=row.id,
                user_id=row.telegram_user_id or 0,
                from_screen=from_screen,
                to_screen=to_screen,
                trigger_type=(row.trigger_type.value if hasattr(row.trigger_type, "value") else str(row.trigger_type)),
                tariff=str(tariff_value) if tariff_value is not None else None,
                created_at=created_at,
            )
        )
    return events


def _normalize_screen_id(screen_id: str | None) -> str:
    if not screen_id:
        return _UNKNOWN_SCREEN
    value = str(screen_id).strip().upper()
    if not value:
        return _UNKNOWN_SCREEN
    if _SCREEN_ID_PATTERN.match(value):
        return value
    return _UNKNOWN_SCREEN


def _group_events_by_user(events: list[EventPoint]) -> dict[int, list[EventPoint]]:
    grouped: dict[int, list[EventPoint]] = {}
    for event in events:
        grouped.setdefault(event.user_id, []).append(event)
    return grouped


def _build_transition_matrix(events: list[EventPoint], unique_users_only: bool) -> list[dict]:
    counts: dict[tuple[str, str], int] = {}
    user_sets: dict[tuple[str, str], set[int]] = {}

    for event in events:
        key = (event.from_screen, event.to_screen)
        counts[key] = counts.get(key, 0) + 1
        user_sets.setdefault(key, set()).add(event.user_id)

    if unique_users_only:
        resolved_counts = {key: len(users) for key, users in user_sets.items()}
    else:
        resolved_counts = counts

    total = sum(resolved_counts.values())
    if total <= 0:
        return []

    items = []
    for (from_screen, to_screen), count in sorted(
        resolved_counts.items(), key=lambda item: item[1], reverse=True
    ):
        share = count / total if total else 0.0
        items.append(
            {
                "from_screen": from_screen,
                "to_screen": to_screen,
                "count": count,
                "share": round(share, 6),
            }
        )
    return items


def _build_funnel(events_by_user: dict[int, list[EventPoint]]) -> list[dict]:
    total_users = len(events_by_user)
    if total_users == 0:
        return []

    step_users: dict[str, int] = {step_name: 0 for step_name, _ in _FUNNEL_STEPS}
    for user_events in events_by_user.values():
        user_progress = _resolve_user_funnel_progress(user_events)
        for step_name, reached in user_progress.items():
            if reached:
                step_users[step_name] += 1

    rows: list[dict] = []
    previous_count = total_users
    for step_name, _ in _FUNNEL_STEPS:
        count = step_users.get(step_name, 0)
        rows.append(
            {
                "step": step_name,
                "users": count,
                "conversion_from_start": round(count / total_users, 6) if total_users else 0.0,
                "conversion_from_previous": round(count / previous_count, 6) if previous_count else 0.0,
            }
        )
        previous_count = count
    return rows


def _resolve_user_funnel_progress(events: list[EventPoint]) -> dict[str, bool]:
    flat_screens: list[str] = []
    for event in events:
        flat_screens.append(event.from_screen)
        flat_screens.append(event.to_screen)

    progress: dict[str, bool] = {}
    search_index = 0
    for step_index, (step_name, accepted_screens) in enumerate(_FUNNEL_STEPS):
        reached = False
        for idx in range(search_index, len(flat_screens)):
            if flat_screens[idx] in accepted_screens:
                reached = True
                search_index = idx + 1
                break
        progress[step_name] = reached
        if not reached:
            for remaining_name, _ in _FUNNEL_STEPS[step_index + 1 :]:
                progress[remaining_name] = False
            break
    for step_name, _ in _FUNNEL_STEPS:
        progress.setdefault(step_name, False)
    return progress


def _build_dropoff(events_by_user: dict[int, list[EventPoint]], filters: AnalyticsFilters) -> list[dict]:
    window_minutes = max(filters.dropoff_window_minutes, 1)
    threshold = timedelta(minutes=window_minutes)
    counts: dict[str, int] = {}
    users_by_screen: dict[str, set[int]] = {}

    for user_id, events in events_by_user.items():
        for index, event in enumerate(events):
            next_event = events[index + 1] if index + 1 < len(events) else None
            should_drop = (
                next_event is None
                or (next_event.created_at - event.created_at) > threshold
            )
            if not should_drop:
                continue
            screen = event.to_screen
            counts[screen] = counts.get(screen, 0) + 1
            users_by_screen.setdefault(screen, set()).add(user_id)

    if filters.unique_users_only:
        resolved_counts = {screen: len(users) for screen, users in users_by_screen.items()}
    else:
        resolved_counts = counts
    total = sum(resolved_counts.values())
    if total <= 0:
        return []

    return [
        {
            "screen": screen,
            "count": count,
            "share": round(count / total, 6),
            "window_minutes": window_minutes,
        }
        for screen, count in sorted(resolved_counts.items(), key=lambda item: item[1], reverse=True)
    ]


def _build_transition_durations(events_by_user: dict[int, list[EventPoint]]) -> list[dict]:
    durations_by_pair: dict[tuple[str, str], list[float]] = {}

    for events in events_by_user.values():
        for index in range(len(events) - 1):
            current_event = events[index]
            next_event = events[index + 1]
            delta_seconds = (next_event.created_at - current_event.created_at).total_seconds()
            if delta_seconds < 0:
                continue
            pair = (current_event.to_screen, next_event.to_screen)
            durations_by_pair.setdefault(pair, []).append(delta_seconds)

    rows: list[dict] = []
    for (from_screen, to_screen), values in sorted(
        durations_by_pair.items(), key=lambda item: len(item[1]), reverse=True
    ):
        if not values:
            continue
        sorted_values = sorted(values)
        rows.append(
            {
                "from_screen": from_screen,
                "to_screen": to_screen,
                "samples": len(sorted_values),
                "median_seconds": round(float(median(sorted_values)), 3),
                "p95_seconds": round(_percentile(sorted_values, 95.0), 3),
            }
        )
    return rows


def _percentile(sorted_values: list[float], percentile_value: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    k = (len(sorted_values) - 1) * (percentile_value / 100.0)
    lower = math.floor(k)
    upper = math.ceil(k)
    if lower == upper:
        return float(sorted_values[int(k)])
    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    return float(lower_value + (upper_value - lower_value) * (k - lower))


def parse_trigger_type(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip().lower()
    if not candidate:
        return None
    try:
        return ScreenTransitionTriggerType(candidate).value
    except ValueError:
        return ScreenTransitionTriggerType.UNKNOWN.value
