from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/api/public", tags=["public"])


def _safe_price(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


@router.get("/tariffs")
async def public_tariffs() -> dict[str, object]:
    prices = settings.tariff_prices_rub
    payload = {
        "currency": "RUB",
        "tariffs": {
            "T0": _safe_price(prices.get("T0"), default=0),
            "T1": _safe_price(prices.get("T1"), default=0),
            "T2": _safe_price(prices.get("T2"), default=0),
            "T3": _safe_price(prices.get("T3"), default=0),
        },
    }
    return payload
