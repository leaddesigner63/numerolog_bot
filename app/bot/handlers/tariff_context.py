from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select

from app.db.models import Order, Tariff, User
from app.db.session import get_session


def resolve_latest_tariff_for_user(
    telegram_user_id: int | None,
    *,
    allowed_tariffs: Iterable[str],
) -> str | None:
    if telegram_user_id is None:
        return None

    allowed_values = {str(value) for value in allowed_tariffs if value is not None}
    if not allowed_values:
        return None

    with get_session() as session:
        user = session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        ).scalar_one_or_none()
        if not user:
            return None

        allowed_tariff_enums = [
            tariff for tariff in Tariff if tariff.value in allowed_values
        ]
        if not allowed_tariff_enums:
            return None

        order = session.execute(
            select(Order)
            .where(
                Order.user_id == user.id,
                Order.tariff.in_(allowed_tariff_enums),
            )
            .order_by(Order.created_at.desc(), Order.id.desc())
        ).scalars().first()
        if not order:
            return None

        return order.tariff.value
