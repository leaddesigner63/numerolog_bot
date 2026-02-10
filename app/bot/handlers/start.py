from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy import select

from app.bot.handlers.screen_manager import screen_manager
from app.bot.handlers.screens import ensure_payment_waiter
from app.db.models import Order, OrderStatus, Report, User
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


def _get_latest_paid_order_and_report(
    telegram_user_id: int,
) -> tuple[dict[str, str] | None, dict[str, str | None] | None]:
    with get_session() as session:
        user = session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        ).scalar_one_or_none()
        if not user:
            return None, None

        latest_paid_order = (
            session.execute(
                select(Order)
                .where(
                    Order.user_id == user.id,
                    Order.status == OrderStatus.PAID,
                )
                .order_by(Order.paid_at.desc(), Order.created_at.desc(), Order.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if not latest_paid_order:
            return None, None

        report = (
            session.execute(
                select(Report)
                .where(Report.order_id == latest_paid_order.id)
                .order_by(Report.created_at.desc(), Report.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        order_state = {
            "selected_tariff": latest_paid_order.tariff.value,
            "order_id": str(latest_paid_order.id),
            "order_status": latest_paid_order.status.value,
        }
        report_state = None
        if report:
            report_state = {
                "report_text": report.report_text,
                "report_model": report.model_used.value if report.model_used else None,
            }
        return order_state, report_state


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
                            "s4_no_inline_keyboard": order.status == OrderStatus.PAID,
                            "payment_processing_notice": order.status != OrderStatus.PAID,
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

    latest_paid_order_state: dict[str, str] | None = None
    latest_report_state: dict[str, str | None] | None = None
    try:
        latest_paid_order_state, latest_report_state = _get_latest_paid_order_and_report(
            message.from_user.id
        )
    except Exception:
        latest_paid_order_state, latest_report_state = None, None

    if latest_paid_order_state:
        state_update = {
            "s4_no_inline_keyboard": False,
            "payment_processing_notice": False,
        }
        state_update.update(latest_paid_order_state)
        if latest_report_state:
            state_update.update(latest_report_state)
        screen_manager.update_state(message.from_user.id, **state_update)
        await screen_manager.show_screen(
            bot=message.bot,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            screen_id="S7" if latest_report_state else "S4",
            trigger_type="message",
            trigger_value="command:/start resume_last_paid_order",
        )
        return

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
