from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy import select

from app.bot.handlers.screen_manager import screen_manager
from app.db.models import Order, OrderStatus, User
from app.db.session import get_session

router = Router()


def _extract_start_payload(message: Message) -> str | None:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1]


def _extract_paywait_order_id(payload: str) -> int | None:
    if not payload.startswith("paywait_"):
        return None
    raw_order_id = payload.split("paywait_", maxsplit=1)[-1]
    try:
        return int(raw_order_id)
    except (TypeError, ValueError):
        return None


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    if not message.from_user:
        return

    payload = _extract_start_payload(message)
    if payload:
        order_id = _extract_paywait_order_id(payload)
        if order_id is not None:
            try:
                with get_session() as session:
                    order = session.execute(
                        select(Order)
                        .join(User, User.id == Order.user_id)
                        .where(
                            Order.id == order_id,
                            User.telegram_user_id == message.from_user.id,
                        )
                    ).scalar_one_or_none()
                    if order:
                        state_snapshot = screen_manager.update_state(message.from_user.id)
                        state_update = {
                            "order_id": str(order.id),
                            "order_status": order.status.value,
                            "selected_tariff": order.tariff.value,
                        }
                        if state_snapshot.data.get("payment_url") is not None:
                            state_update["payment_url"] = state_snapshot.data.get("payment_url")
                        screen_manager.update_state(message.from_user.id, **state_update)
                        await screen_manager.show_screen(
                            bot=message.bot,
                            chat_id=message.chat.id,
                            user_id=message.from_user.id,
                            screen_id=("S4" if order.status == OrderStatus.PAID else "S3"),
                            trigger_type="message",
                            trigger_value=f"command:/start payload:{payload}",
                        )
                        return
            except Exception:
                # Мягкий fallback в S0 для любых сбоев чтения payload/БД.
                pass

    await screen_manager.show_screen(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        screen_id="S0",
        trigger_type="message",
        trigger_value="command:/start",
    )
