from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy import select

from app.bot.handlers.screen_manager import screen_manager
from app.bot.handlers.screens import ensure_payment_waiter
from app.db.models import Order, OrderStatus, User, UserFirstTouchAttribution
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


def _parse_first_touch_payload(payload: str | None) -> dict[str, object]:
    raw_payload = payload or ""
    raw_parts = raw_payload.split("_") if raw_payload else []
    source = raw_parts[0] if len(raw_parts) > 0 and raw_parts[0] else None
    campaign = raw_parts[1] if len(raw_parts) > 1 and raw_parts[1] else None
    placement = "_".join(raw_parts[2:]) if len(raw_parts) > 2 else None
    if placement == "":
        placement = None
    return {
        "start_payload": raw_payload,
        "source": source,
        "campaign": campaign,
        "placement": placement,
        "raw_parts": raw_parts,
    }


def _capture_first_touch_attribution(telegram_user_id: int, payload: str | None) -> None:
    parsed_payload = _parse_first_touch_payload(payload)
    with get_session() as session:
        existing = session.execute(
            select(UserFirstTouchAttribution.id).where(
                UserFirstTouchAttribution.telegram_user_id == telegram_user_id
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        session.add(
            UserFirstTouchAttribution(
                telegram_user_id=telegram_user_id,
                start_payload=str(parsed_payload.get("start_payload") or ""),
                source=parsed_payload.get("source"),
                campaign=parsed_payload.get("campaign"),
                placement=parsed_payload.get("placement"),
                raw_parts=parsed_payload.get("raw_parts"),
            )
        )


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    if not message.from_user:
        return

    payload = _extract_start_payload(message)
    try:
        _capture_first_touch_attribution(message.from_user.id, payload)
    except Exception:
        pass

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
                        should_resume_report_flow = order.status == OrderStatus.PAID
                        state_update = {
                            "order_id": str(order.id),
                            "order_status": order.status.value,
                            "selected_tariff": order.tariff.value,
                            "s4_no_inline_keyboard": False,
                            "payment_processing_notice": order.status != OrderStatus.PAID,
                            "profile_flow": "report" if should_resume_report_flow else None,
                        }
                        if state_snapshot.data.get("payment_url") is not None:
                            state_update["payment_url"] = state_snapshot.data.get("payment_url")
                        screen_manager.update_state(message.from_user.id, **state_update)
                        target_screen = "S4" if order.status == OrderStatus.PAID else "S3"
                        await screen_manager.show_screen(
                            bot=message.bot,
                            chat_id=message.chat.id,
                            user_id=message.from_user.id,
                            screen_id=target_screen,
                            trigger_type="message",
                            trigger_value=f"command:/start payload:{payload}",
                        )
                        if target_screen == "S3":
                            await ensure_payment_waiter(
                                bot=message.bot,
                                chat_id=message.chat.id,
                                user_id=message.from_user.id,
                            )
                        return
            except Exception:
                # Мягкий fallback в S0 для любых сбоев чтения payload/БД.
                pass

    screen_manager.update_state(
        message.from_user.id,
        s4_no_inline_keyboard=False,
        payment_processing_notice=False,
    )
    await screen_manager.show_screen(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        screen_id="S0",
        trigger_type="message",
        trigger_value="command:/start",
    )
