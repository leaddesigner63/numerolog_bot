from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy import select
from datetime import datetime, timezone

from app.bot.handlers.screen_manager import screen_manager
from app.bot.handlers.screens import ensure_payment_waiter
from app.db.models import (
    Order,
    OrderStatus,
    QuestionnaireResponse,
    QuestionnaireStatus,
    ReportJob,
    ReportJobStatus,
    Tariff,
    User,
    UserProfile,
)
from app.db.session import get_session
from app.services.traffic_attribution import save_user_first_touch_attribution

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
    raw_order_id = payload.split("paywait_", 1)[-1]
    try:
        return int(raw_order_id)
    except (TypeError, ValueError):
        return None


def _extract_resume_nudge_order_id(payload: str) -> int | None:
    if not payload.startswith("resume_nudge"):
        return None
    if payload == "resume_nudge":
        return None
    if not payload.startswith("resume_nudge_"):
        return None
    raw_order_id = payload.split("resume_nudge_", 1)[-1]
    try:
        return int(raw_order_id)
    except (TypeError, ValueError):
        return None


def _create_paid_order_report_job(
    session,
    *,
    order: Order,
    chat_id: int,
) -> ReportJob:
    job = ReportJob(
        user_id=order.user_id,
        order_id=order.id,
        tariff=order.tariff,
        status=ReportJobStatus.PENDING,
        attempts=0,
        chat_id=chat_id,
    )
    session.add(job)
    session.flush()
    return job


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    if not message.from_user:
        return

    payload = _extract_start_payload(message)
    try:
        save_user_first_touch_attribution(
            message.from_user.id,
            payload,
            telegram_username=getattr(message.from_user, "username", None),
        )
    except Exception:
        pass

    if payload:
        if payload.startswith("resume_nudge"):
            screen_manager.update_state(
                message.from_user.id,
                resume_after_nudge_at=datetime.now(timezone.utc).isoformat(),
                resume_after_nudge_payload=payload,
            )
        order_id = _extract_paywait_order_id(payload)
        if order_id is None:
            order_id = _extract_resume_nudge_order_id(payload)
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
                        target_screen = "S3"
                        latest_job = None
                        if should_resume_report_flow:
                            profile = session.execute(
                                select(UserProfile).where(UserProfile.user_id == order.user_id).limit(1)
                            ).scalar_one_or_none()
                            questionnaire = None
                            if order.tariff in {Tariff.T2, Tariff.T3}:
                                questionnaire = session.execute(
                                    select(QuestionnaireResponse)
                                    .where(QuestionnaireResponse.user_id == order.user_id)
                                    .order_by(QuestionnaireResponse.id.desc())
                                    .limit(1)
                                ).scalar_one_or_none()
                            latest_job = session.execute(
                                select(ReportJob)
                                .where(
                                    ReportJob.user_id == order.user_id,
                                    ReportJob.order_id == order.id,
                                )
                                .order_by(ReportJob.id.desc())
                                .limit(1)
                            ).scalar_one_or_none()
                            if profile is None:
                                target_screen = "S4"
                            elif (
                                order.tariff in {Tariff.T2, Tariff.T3}
                                and (
                                    questionnaire is None
                                    or questionnaire.status != QuestionnaireStatus.COMPLETED
                                )
                            ):
                                target_screen = "S5"
                            elif latest_job is None:
                                latest_job = _create_paid_order_report_job(
                                    session,
                                    order=order,
                                    chat_id=message.chat.id,
                                )
                                target_screen = "S6"
                            elif latest_job.status == ReportJobStatus.COMPLETED:
                                target_screen = "S7"
                            elif latest_job.status in {
                                ReportJobStatus.PENDING,
                                ReportJobStatus.IN_PROGRESS,
                            }:
                                target_screen = "S6"
                            else:
                                latest_job = _create_paid_order_report_job(
                                    session,
                                    order=order,
                                    chat_id=message.chat.id,
                                )
                                target_screen = "S6"
                        state_update = {
                            "order_id": str(order.id),
                            "order_status": order.status.value,
                            "order_amount": str(order.amount),
                            "order_currency": order.currency,
                            "selected_tariff": order.tariff.value,
                            "s4_no_inline_keyboard": False,
                            "payment_processing_notice": order.status != OrderStatus.PAID,
                            "profile_flow": "report" if should_resume_report_flow else None,
                            "report_job_id": str(latest_job.id) if latest_job else None,
                            "report_job_status": latest_job.status.value if latest_job else None,
                            "report_job_attempts": latest_job.attempts if latest_job else None,
                        }
                        if state_snapshot.data.get("payment_url") is not None:
                            state_update["payment_url"] = state_snapshot.data.get("payment_url")
                        screen_manager.update_state(message.from_user.id, **state_update)
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
