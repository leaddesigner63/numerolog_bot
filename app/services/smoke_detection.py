from __future__ import annotations

from sqlalchemy import Text, cast, or_, select
from sqlalchemy.orm import Session

from app.db.models import Order, ScreenStateRecord, User, UserProfile

SMOKE_ORDER_PROVIDER_PREFIX = "smoke-"
SMOKE_PROFILE_NAME = "Smoke Check"
SMOKE_MARKER_KEY = "smoke_marker"


def _smoke_order_filter():
    return or_(
        Order.is_smoke_check.is_(True),
        Order.provider_payment_id.startswith(SMOKE_ORDER_PROVIDER_PREFIX),
    )


def _smoke_state_filter():
    return cast(ScreenStateRecord.data, Text).like(f'%"{SMOKE_MARKER_KEY}":%')


def collect_smoke_telegram_ids(session: Session) -> set[int]:
    rows = session.scalars(
        select(ScreenStateRecord.telegram_user_id).where(_smoke_state_filter())
    )
    return {int(telegram_id) for telegram_id in rows if telegram_id is not None}


def collect_smoke_user_ids(session: Session) -> set[int]:
    smoke_user_ids = {
        int(user_id)
        for user_id in session.scalars(select(Order.user_id).where(_smoke_order_filter()))
        if user_id is not None
    }
    smoke_user_ids.update(
        int(user_id)
        for user_id in session.scalars(
            select(UserProfile.user_id).where(UserProfile.name == SMOKE_PROFILE_NAME)
        )
        if user_id is not None
    )

    smoke_telegram_ids = collect_smoke_telegram_ids(session)
    if smoke_telegram_ids:
        smoke_user_ids.update(
            int(user_id)
            for user_id in session.scalars(
                select(User.id).where(User.telegram_user_id.in_(smoke_telegram_ids))
            )
            if user_id is not None
        )
    return smoke_user_ids


def collect_explicit_smoke_order_ids(session: Session) -> set[int]:
    return {
        int(order_id)
        for order_id in session.scalars(select(Order.id).where(_smoke_order_filter()))
        if order_id is not None
    }


def collect_smoke_order_ids(session: Session) -> set[int]:
    smoke_order_ids = collect_explicit_smoke_order_ids(session)
    smoke_user_ids = collect_smoke_user_ids(session)
    if smoke_user_ids:
        smoke_order_ids.update(
            int(order_id)
            for order_id in session.scalars(
                select(Order.id).where(Order.user_id.in_(smoke_user_ids))
            )
            if order_id is not None
        )
    return smoke_order_ids
