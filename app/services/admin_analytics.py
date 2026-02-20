from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    MarketingConsentEvent,
    MarketingConsentEventType,
    Order,
    OrderStatus,
    PaymentConfirmationSource,
    ScreenTransitionEvent,
    ScreenTransitionTriggerType,
    User,
    UserFirstTouchAttribution,
    UserProfile,
)


_UNKNOWN_SCREEN = "UNKNOWN"
_SCREEN_ID_PATTERN = re.compile(r"^S\d+(?:_T[0-3])?$")
_FUNNEL_STEPS: list[tuple[str, set[str]]] = [
    ("S0", {"S0"}),
    ("S1", {"S1"}),
    ("S3", {"S3"}),
    ("S5", {"S5"}),
    ("S6_OR_S7", {"S6", "S7"}),
]
_FINANCE_ENTRY_SCREENS = {"S3", "S4"}
_S3_REPORT_DETAILS_TRIGGER = "s3:report_details"
_PROVIDER_CONFIRMATION_SOURCES = {
    PaymentConfirmationSource.PROVIDER_WEBHOOK,
    PaymentConfirmationSource.PROVIDER_POLL,
}


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


@dataclass(frozen=True)
class FinanceOrderPoint:
    id: int
    user_id: int
    tariff: str
    amount: float
    confirmed_at: datetime


@dataclass(frozen=True)
class FinanceAnalyticsFilters:
    from_dt: datetime | None = None
    to_dt: datetime | None = None
    tariff: str | None = None


@dataclass(frozen=True)
class MarketingAnalyticsFilters:
    from_dt: datetime | None = None
    to_dt: datetime | None = None


@dataclass(frozen=True)
class TrafficAnalyticsFilters:
    from_dt: datetime | None = None
    to_dt: datetime | None = None
    tariff: str | None = None


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


def build_finance_analytics(session: Session, filters: FinanceAnalyticsFilters) -> dict:
    entries = _load_finance_entries(session, filters)
    confirmed_orders = _load_provider_confirmed_orders(session, filters)
    reached_users = {item.user_id for item in entries}
    paid_users = {item.user_id for item in confirmed_orders}
    conversion = (len(paid_users) / len(reached_users)) if reached_users else 0.0

    report_details_clicks, report_details_users = _count_s3_report_details_clicks(session, filters)

    return {
        "summary": {
            "entry_screens": sorted(_FINANCE_ENTRY_SCREENS),
            "entry_users": len(reached_users),
            "provider_confirmed_orders": len(confirmed_orders),
            "provider_confirmed_users": len(paid_users),
            "conversion_to_provider_confirmed": round(conversion, 6),
            "provider_confirmed_revenue": round(sum(item.amount for item in confirmed_orders), 2),
            "s3_report_details_clicks": report_details_clicks,
            "s3_report_details_users": report_details_users,
            "data_source": "provider_confirmed_only",
        },
        "by_tariff": _build_revenue_by_tariff(confirmed_orders),
        "timeseries": _build_finance_timeseries(entries, confirmed_orders),
    }


def build_marketing_subscription_analytics(session: Session, filters: MarketingAnalyticsFilters) -> dict:
    total_subscribed = _count_total_subscribed(session)
    period_new_subscribes = _count_consent_events(session, filters, MarketingConsentEventType.ACCEPTED)
    period_unsubscribes = _count_consent_events(session, filters, MarketingConsentEventType.REVOKED)
    prompted_users = _count_prompted_users(session, filters)
    prompt_subscribes = _count_prompt_subscribes(session, filters)
    conversion_rate = (prompt_subscribes / prompted_users) if prompted_users else 0.0
    return {
        "total_subscribed": total_subscribed,
        "new_subscribes_per_period": period_new_subscribes,
        "unsubscribes_per_period": period_unsubscribes,
        "prompt_to_subscribe_conversion_rate": round(conversion_rate, 6),
        "prompted_users_per_period": prompted_users,
        "subscribed_from_prompt_per_period": prompt_subscribes,
    }


def build_traffic_analytics(session: Session, filters: TrafficAnalyticsFilters) -> dict:
    first_touch = _load_first_touch_entries(session, filters)
    if not first_touch:
        return {
            "users_started_total": 0,
            "users_by_source": [],
            "users_by_source_campaign": [],
            "conversions": [],
        }

    base_user_ids = {item.telegram_user_id for item in first_touch}
    paid_telegram_user_ids = _load_paid_telegram_user_ids(session, filters, base_user_ids)
    users_by_source = _build_users_by_source(first_touch, paid_telegram_user_ids)
    users_by_source_campaign = _build_users_by_source_campaign(first_touch, paid_telegram_user_ids)
    conversions = _build_first_touch_conversions(session, filters, base_user_ids, paid_telegram_user_ids)
    return {
        "users_started_total": len(base_user_ids),
        "users_by_source": users_by_source,
        "users_by_source_campaign": users_by_source_campaign,
        "conversions": conversions,
    }


def _load_first_touch_entries(session: Session, filters: TrafficAnalyticsFilters) -> list[UserFirstTouchAttribution]:
    query: Select[tuple[UserFirstTouchAttribution]] = select(UserFirstTouchAttribution)
    if filters.from_dt:
        query = query.where(UserFirstTouchAttribution.captured_at >= filters.from_dt)
    if filters.to_dt:
        query = query.where(UserFirstTouchAttribution.captured_at <= filters.to_dt)
    query = query.order_by(UserFirstTouchAttribution.captured_at.asc(), UserFirstTouchAttribution.id.asc())

    items = session.execute(query).scalars().all()
    if not items:
        return []

    admin_ids = _parse_admin_ids(settings.admin_ids)
    filtered = [item for item in items if item.telegram_user_id not in admin_ids]
    if not filters.tariff:
        return filtered

    allowed_user_ids = _load_user_ids_by_tariff(session, filters)
    if not allowed_user_ids:
        return []
    return [item for item in filtered if item.telegram_user_id in allowed_user_ids]


def _load_user_ids_by_tariff(session: Session, filters: TrafficAnalyticsFilters) -> set[int]:
    tariff_value = str(filters.tariff or "").upper()
    if not tariff_value:
        return set()

    event_filters = AnalyticsFilters(from_dt=filters.from_dt, to_dt=filters.to_dt, tariff=tariff_value)
    traffic_user_ids = {item.user_id for item in _load_events(session, event_filters)}

    order_filters = FinanceAnalyticsFilters(from_dt=filters.from_dt, to_dt=filters.to_dt, tariff=tariff_value)
    order_points = _load_provider_confirmed_orders(session, order_filters)
    if order_points:
        user_rows = session.execute(select(User).where(User.id.in_({item.user_id for item in order_points}))).scalars().all()
        traffic_user_ids.update({user.telegram_user_id for user in user_rows})

    return traffic_user_ids


def _normalize_traffic_value(value: str | None) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate else "UNKNOWN"


def _load_paid_telegram_user_ids(
    session: Session,
    filters: TrafficAnalyticsFilters,
    base_user_ids: set[int],
) -> set[int]:
    order_filters = FinanceAnalyticsFilters(from_dt=filters.from_dt, to_dt=filters.to_dt, tariff=filters.tariff)
    paid_orders = _load_provider_confirmed_orders(session, order_filters)
    paid_user_ids = {item.user_id for item in paid_orders}
    if not paid_user_ids:
        return set()

    users = session.execute(select(User).where(User.id.in_(paid_user_ids))).scalars().all()
    return {user.telegram_user_id for user in users if user.telegram_user_id in base_user_ids}


def _build_users_by_source(items: list[UserFirstTouchAttribution], paid_telegram_user_ids: set[int]) -> list[dict]:
    grouped: dict[str, set[int]] = {}
    for item in items:
        source = _normalize_traffic_value(item.source)
        grouped.setdefault(source, set()).add(item.telegram_user_id)
    return [
        {
            "source": source,
            "users": len(user_ids),
            "conversion_to_paid": round((len(user_ids & paid_telegram_user_ids) / len(user_ids)) if user_ids else 0.0, 6),
        }
        for source, user_ids in sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0]))
    ]


def _build_users_by_source_campaign(items: list[UserFirstTouchAttribution], paid_telegram_user_ids: set[int]) -> list[dict]:
    grouped: dict[tuple[str, str], set[int]] = {}
    for item in items:
        source = _normalize_traffic_value(item.source)
        campaign = _normalize_traffic_value(item.campaign)
        grouped.setdefault((source, campaign), set()).add(item.telegram_user_id)
    return [
        {
            "source": source,
            "campaign": campaign,
            "users": len(user_ids),
            "conversion": round((len(user_ids & paid_telegram_user_ids) / len(user_ids)) if user_ids else 0.0, 6),
        }
        for (source, campaign), user_ids in sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0][0], pair[0][1]))
    ]


def _build_first_touch_conversions(
    session: Session,
    filters: TrafficAnalyticsFilters,
    base_user_ids: set[int],
    paid_users: set[int],
) -> list[dict]:
    total = len(base_user_ids)
    if total == 0:
        return []

    event_filters = AnalyticsFilters(from_dt=filters.from_dt, to_dt=filters.to_dt, tariff=filters.tariff)
    events = _load_events(session, event_filters)
    reached_tariff_users = {
        event.user_id
        for event in events
        if event.user_id in base_user_ids and (event.from_screen in _FINANCE_ENTRY_SCREENS or event.to_screen in _FINANCE_ENTRY_SCREENS)
    }

    rows: list[dict] = []
    steps = [
        ("started", base_user_ids),
        ("reached_tariff", reached_tariff_users),
        ("paid", paid_users),
    ]
    prev_users = total
    for step_name, user_ids in steps:
        count = len(user_ids)
        rows.append(
            {
                "step": step_name,
                "users": count,
                "conversion_from_start": round((count / total) if total else 0.0, 6),
                "conversion_from_previous": round((count / prev_users) if prev_users else 0.0, 6),
            }
        )
        prev_users = count
    return rows


def _count_total_subscribed(session: Session) -> int:
    value = session.execute(
        select(UserProfile)
        .where(
            UserProfile.marketing_consent_accepted_at.is_not(None),
            UserProfile.marketing_consent_revoked_at.is_(None),
        )
    ).scalars().all()
    return len(value)


def _count_consent_events(
    session: Session,
    filters: MarketingAnalyticsFilters,
    event_type: MarketingConsentEventType,
) -> int:
    query: Select[tuple[MarketingConsentEvent]] = select(MarketingConsentEvent).where(
        MarketingConsentEvent.event_type == event_type,
    )
    if filters.from_dt:
        query = query.where(MarketingConsentEvent.event_at >= filters.from_dt)
    if filters.to_dt:
        query = query.where(MarketingConsentEvent.event_at <= filters.to_dt)
    return len(session.execute(query).scalars().all())


def _count_prompted_users(session: Session, filters: MarketingAnalyticsFilters) -> int:
    query: Select[tuple[ScreenTransitionEvent]] = select(ScreenTransitionEvent).where(
        (ScreenTransitionEvent.from_screen_id == "S4") | (ScreenTransitionEvent.to_screen_id == "S4")
    )
    if filters.from_dt:
        query = query.where(ScreenTransitionEvent.created_at >= filters.from_dt)
    if filters.to_dt:
        query = query.where(ScreenTransitionEvent.created_at <= filters.to_dt)
    rows = session.execute(query).scalars().all()
    return len({int(row.telegram_user_id or 0) for row in rows if row.telegram_user_id})


def _count_prompt_subscribes(session: Session, filters: MarketingAnalyticsFilters) -> int:
    query: Select[tuple[MarketingConsentEvent]] = select(MarketingConsentEvent).where(
        MarketingConsentEvent.event_type == MarketingConsentEventType.ACCEPTED,
        MarketingConsentEvent.source == "marketing_prompt",
    )
    if filters.from_dt:
        query = query.where(MarketingConsentEvent.event_at >= filters.from_dt)
    if filters.to_dt:
        query = query.where(MarketingConsentEvent.event_at <= filters.to_dt)
    return len(session.execute(query).scalars().all())




def _count_s3_report_details_clicks(
    session: Session,
    filters: FinanceAnalyticsFilters,
) -> tuple[int, int]:
    query: Select[tuple[ScreenTransitionEvent]] = select(ScreenTransitionEvent).where(
        ScreenTransitionEvent.trigger_value == _S3_REPORT_DETAILS_TRIGGER,
    )
    if filters.from_dt:
        query = query.where(ScreenTransitionEvent.created_at >= filters.from_dt)
    if filters.to_dt:
        query = query.where(ScreenTransitionEvent.created_at <= filters.to_dt)

    rows = session.execute(query).scalars().all()
    if not rows:
        return 0, 0

    admin_ids = _parse_admin_ids(settings.admin_ids)
    filtered_rows = [row for row in rows if int(row.telegram_user_id or 0) not in admin_ids]
    if not filtered_rows:
        return 0, 0

    if filters.tariff:
        expected_tariff = str(filters.tariff).upper()
        filtered_rows = [
            row
            for row in filtered_rows
            if str((row.metadata_json or {}).get("tariff") or "").upper() == expected_tariff
        ]

    if not filtered_rows:
        return 0, 0

    return len(filtered_rows), len({int(row.telegram_user_id or 0) for row in filtered_rows if row.telegram_user_id})

def _load_finance_entries(session: Session, filters: FinanceAnalyticsFilters) -> list[EventPoint]:
    event_filters = AnalyticsFilters(from_dt=filters.from_dt, to_dt=filters.to_dt, tariff=filters.tariff)
    events = _load_events(session, event_filters)
    entries: list[EventPoint] = []
    seen_user_ids: set[int] = set()
    for event in events:
        if event.user_id in seen_user_ids:
            continue
        if event.from_screen in _FINANCE_ENTRY_SCREENS or event.to_screen in _FINANCE_ENTRY_SCREENS:
            seen_user_ids.add(event.user_id)
            entries.append(event)
    return entries


def _load_provider_confirmed_orders(session: Session, filters: FinanceAnalyticsFilters) -> list[FinanceOrderPoint]:
    query: Select[tuple[Order]] = select(Order).where(
        Order.status == OrderStatus.PAID,
        Order.payment_confirmation_source.in_(list(_PROVIDER_CONFIRMATION_SOURCES)),
    )
    if filters.from_dt:
        query = query.where(Order.payment_confirmed_at >= filters.from_dt)
    if filters.to_dt:
        query = query.where(Order.payment_confirmed_at <= filters.to_dt)
    if filters.tariff:
        query = query.where(Order.tariff == filters.tariff.upper())
    rows = session.execute(query.order_by(Order.payment_confirmed_at.asc(), Order.id.asc())).scalars().all()

    points: list[FinanceOrderPoint] = []
    for row in rows:
        confirmed_at = row.payment_confirmed_at or row.paid_at or row.created_at or datetime.now(timezone.utc)
        points.append(
            FinanceOrderPoint(
                id=row.id,
                user_id=row.user_id,
                tariff=(row.tariff.value if hasattr(row.tariff, "value") else str(row.tariff)).upper(),
                amount=float(row.amount or 0),
                confirmed_at=confirmed_at,
            )
        )
    return points


def _build_revenue_by_tariff(orders: list[FinanceOrderPoint]) -> list[dict]:
    grouped: dict[str, dict[str, float]] = {}
    for item in orders:
        bucket = grouped.setdefault(item.tariff, {"orders": 0, "revenue": 0.0})
        bucket["orders"] += 1
        bucket["revenue"] += item.amount
    return [
        {
            "tariff": tariff,
            "provider_confirmed_orders": int(stats["orders"]),
            "provider_confirmed_revenue": round(float(stats["revenue"]), 2),
            "avg_check": round(float(stats["revenue"]) / float(stats["orders"]), 2) if stats["orders"] else 0.0,
            "data_source": "provider_confirmed_only",
        }
        for tariff, stats in sorted(grouped.items(), key=lambda item: item[0])
    ]


def _build_finance_timeseries(entries: list[EventPoint], orders: list[FinanceOrderPoint]) -> list[dict]:
    days: dict[str, dict[str, object]] = {}

    for item in entries:
        day = item.created_at.date().isoformat()
        day_bucket = days.setdefault(day, {"entry_users": set(), "provider_confirmed_orders": 0, "provider_confirmed_revenue": 0.0})
        day_bucket["entry_users"].add(item.user_id)

    for item in orders:
        day = item.confirmed_at.date().isoformat()
        day_bucket = days.setdefault(day, {"entry_users": set(), "provider_confirmed_orders": 0, "provider_confirmed_revenue": 0.0})
        day_bucket["provider_confirmed_orders"] = int(day_bucket["provider_confirmed_orders"]) + 1
        day_bucket["provider_confirmed_revenue"] = float(day_bucket["provider_confirmed_revenue"]) + item.amount

    rows: list[dict] = []
    for day in sorted(days.keys()):
        entry_users = len(days[day]["entry_users"])
        confirmed_orders = int(days[day]["provider_confirmed_orders"])
        conversion = (confirmed_orders / entry_users) if entry_users else 0.0
        rows.append(
            {
                "date": day,
                "entry_users": entry_users,
                "provider_confirmed_orders": confirmed_orders,
                "provider_confirmed_revenue": round(float(days[day]["provider_confirmed_revenue"]), 2),
                "conversion_to_provider_confirmed": round(conversion, 6),
                "data_source": "provider_confirmed_only",
            }
        )
    return rows


def _load_events(session: Session, filters: AnalyticsFilters) -> list[EventPoint]:
    admin_ids = _parse_admin_ids(settings.admin_ids)
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
        telegram_user_id = row.telegram_user_id or 0
        if telegram_user_id in admin_ids:
            continue
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
                user_id=telegram_user_id,
                from_screen=from_screen,
                to_screen=to_screen,
                trigger_type=(row.trigger_type.value if hasattr(row.trigger_type, "value") else str(row.trigger_type)),
                tariff=str(tariff_value) if tariff_value is not None else None,
                created_at=created_at,
            )
        )
    return events


def _parse_admin_ids(raw_value: str | None) -> set[int]:
    if not raw_value:
        return set()
    admin_ids: set[int] = set()
    for item in raw_value.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            admin_ids.add(int(candidate))
        except ValueError:
            continue
    return admin_ids


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
