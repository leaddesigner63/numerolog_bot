from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile, Message

from app.bot.markdown import render_markdown_to_html
from app.bot.screen_images import resolve_screen_image_path
from app.bot.screens import SCREEN_REGISTRY, ScreenContent
from app.db.models import (
    ScreenStateRecord,
    ScreenTransitionEvent,
    ScreenTransitionStatus,
    ScreenTransitionTriggerType,
)
from app.db.session import get_session


@dataclass
class ScreenState:
    screen_id: str | None = None
    message_ids: list[int] = field(default_factory=list)
    user_message_ids: list[int] = field(default_factory=list)
    last_question_message_id: int | None = None
    data: dict[str, Any] = field(default_factory=dict)


class ScreenStateStore:
    def __init__(self) -> None:
        self._states: dict[int, ScreenState] = {}

    def get_state(self, user_id: int) -> ScreenState:
        if user_id not in self._states:
            self._states[user_id] = self._load_state(user_id)
        return self._states[user_id]

    def update_data(self, user_id: int, **kwargs: Any) -> ScreenState:
        state = self.get_state(user_id)
        state.data.update(kwargs)
        self._persist_state(user_id, state)
        return state

    def update_screen(
        self, user_id: int, screen_id: str, message_ids: list[int]
    ) -> ScreenState:
        state = self.get_state(user_id)
        state.screen_id = screen_id
        state.message_ids = message_ids
        self._persist_state(user_id, state)
        return state

    def add_screen_message_id(self, user_id: int, message_id: int) -> ScreenState:
        state = self.get_state(user_id)
        state.message_ids.append(message_id)
        self._persist_state(user_id, state)
        return state

    def remove_screen_message_id(self, user_id: int, message_id: int) -> ScreenState:
        state = self.get_state(user_id)
        if message_id in state.message_ids:
            state.message_ids = [mid for mid in state.message_ids if mid != message_id]
            self._persist_state(user_id, state)
        return state

    def add_user_message_id(self, user_id: int, message_id: int) -> ScreenState:
        state = self.get_state(user_id)
        state.user_message_ids.append(message_id)
        self._persist_state(user_id, state)
        return state

    def remove_user_message_id(self, user_id: int, message_id: int) -> ScreenState:
        state = self.get_state(user_id)
        if message_id in state.user_message_ids:
            state.user_message_ids = [
                mid for mid in state.user_message_ids if mid != message_id
            ]
            self._persist_state(user_id, state)
        return state

    def add_pdf_message_id(self, user_id: int, message_id: int) -> ScreenState:
        state = self.get_state(user_id)
        pdf_message_ids = list(state.data.get("pdf_message_ids") or [])
        pdf_message_ids.append(message_id)
        state.data["pdf_message_ids"] = pdf_message_ids
        self._persist_state(user_id, state)
        return state

    def pop_pdf_message_ids(self, user_id: int) -> list[int]:
        state = self.get_state(user_id)
        pdf_message_ids = list(state.data.get("pdf_message_ids") or [])
        if "pdf_message_ids" in state.data:
            state.data.pop("pdf_message_ids", None)
            self._persist_state(user_id, state)
        return pdf_message_ids

    def clear_message_ids(self, user_id: int) -> None:
        state = self.get_state(user_id)
        if not state.message_ids:
            return
        state.message_ids = []
        self._persist_state(user_id, state)

    def clear_user_message_ids(self, user_id: int) -> None:
        state = self.get_state(user_id)
        if not state.user_message_ids:
            return
        state.user_message_ids = []
        self._persist_state(user_id, state)

    def update_last_question_message_id(
        self, user_id: int, message_id: int | None
    ) -> ScreenState:
        state = self.get_state(user_id)
        state.last_question_message_id = message_id
        self._persist_state(user_id, state)
        return state

    def clear_last_question_message_id(self, user_id: int) -> None:
        state = self.get_state(user_id)
        if state.last_question_message_id is None:
            return
        state.last_question_message_id = None
        self._persist_state(user_id, state)

    def clear_state(self, user_id: int) -> None:
        if user_id in self._states:
            del self._states[user_id]
        with get_session() as session:
            record = session.get(ScreenStateRecord, user_id)
            if record:
                session.delete(record)
                session.flush()

    def _load_state(self, user_id: int) -> ScreenState:
        with get_session() as session:
            record = session.get(ScreenStateRecord, user_id)
            if not record:
                return ScreenState()
            return ScreenState(
                screen_id=record.screen_id,
                message_ids=list(record.message_ids or []),
                user_message_ids=list(record.user_message_ids or []),
                last_question_message_id=record.last_question_message_id,
                data=dict(record.data or {}),
            )

    def _persist_state(self, user_id: int, state: ScreenState) -> None:
        with get_session() as session:
            record = session.get(ScreenStateRecord, user_id)
            if record:
                record.screen_id = state.screen_id
                record.message_ids = state.message_ids
                record.user_message_ids = state.user_message_ids
                record.last_question_message_id = state.last_question_message_id
                record.data = state.data
            else:
                record = ScreenStateRecord(
                    telegram_user_id=user_id,
                    screen_id=state.screen_id,
                    message_ids=state.message_ids,
                    user_message_ids=state.user_message_ids,
                    last_question_message_id=state.last_question_message_id,
                    data=state.data,
                )
                session.add(record)
            session.flush()


class ScreenManager:
    CleanupMode = Literal["remove_keyboard_only", "delete_messages"]
    _telegram_message_limit = 4096
    _telegram_caption_limit = 1024
    _critical_screens: dict[str, str] = {
        "S1": "before_tariff_selection",
        "S3": "before_payment",
        "S5": "before_payment",
    }

    def __init__(self, store: ScreenStateStore | None = None) -> None:
        self._store = store or ScreenStateStore()
        self._logger = logging.getLogger(__name__)

    def render_screen(
        self, screen_id: str, user_id: int, state: dict[str, Any]
    ) -> ScreenContent:
        screen_fn = SCREEN_REGISTRY.get(screen_id)
        if not screen_fn:
            raise ValueError(f"Unknown screen id: {screen_id}")
        content = screen_fn(state)
        rendered_messages = [
            render_markdown_to_html(message)
            for message in content.messages
            if message is not None
        ]
        parse_mode = content.parse_mode or "HTML"
        return ScreenContent(
            messages=rendered_messages,
            keyboard=content.keyboard,
            parse_mode=parse_mode,
            image_path=content.image_path,
        )

    async def show_screen(
        self,
        bot: Bot,
        chat_id: int,
        user_id: int,
        screen_id: str,
        *,
        trigger_type: ScreenTransitionTriggerType | str | None = None,
        trigger_value: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> bool:
        state = self._store.get_state(user_id)
        from_screen = state.screen_id
        to_screen = screen_id
        safe_metadata = self._enrich_metadata_with_tariff(
            metadata_json=metadata_json,
            state_data=state.data,
        )

        try:
            content = self.render_screen(screen_id, user_id, state.data)
        except Exception as exc:
            safe_metadata.setdefault("reason", "screen_render_failed")
            safe_metadata.setdefault("error", str(exc))
            self._record_transition_event(
                user_id=user_id,
                from_screen=from_screen,
                to_screen=to_screen,
                trigger_type=trigger_type,
                trigger_value=trigger_value,
                transition_status=ScreenTransitionStatus.ERROR,
                metadata_json=safe_metadata,
            )
            self._logger.warning(
                "screen_render_failed",
                extra={"user_id": user_id, "screen_id": to_screen, "error": str(exc)},
            )
            return False
        image_path = resolve_screen_image_path(screen_id, state.data)
        delivered = False

        pdf_message_ids = self._store.pop_pdf_message_ids(user_id)
        pdf_notice_required = bool(pdf_message_ids)
        previous_message_ids = list(state.message_ids)
        previous_user_message_ids = list(state.user_message_ids)
        last_question_message_id = state.last_question_message_id
        failed_message_ids: list[int] = []
        for message_id in pdf_message_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
                self._logger.info(
                    "pdf_cleanup_failed",
                    extra={
                        "user_id": user_id,
                        "screen_id": state.screen_id,
                        "message_id": message_id,
                        "error": str(exc),
                    },
                )
        for message_id in previous_message_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
                failed_message_ids.append(message_id)
                self._logger.info(
                    "screen_cleanup_failed",
                    extra={
                        "user_id": user_id,
                        "screen_id": state.screen_id,
                        "message_id": message_id,
                        "error": str(exc),
                    },
                )

        retry_failed_message_ids: list[int] = []
        for message_id in failed_message_ids:
            if await self._retry_delete_message(bot, chat_id, message_id):
                continue
            retry_failed_message_ids.append(message_id)
        failed_message_ids = retry_failed_message_ids

        failed_user_message_ids: list[int] = []
        for message_id in previous_user_message_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
                failed_user_message_ids.append(message_id)
                self._logger.info(
                    "user_message_cleanup_failed",
                    extra={
                        "user_id": user_id,
                        "screen_id": state.screen_id,
                        "message_id": message_id,
                        "error": str(exc),
                    },
                )

        retry_failed_user_message_ids: list[int] = []
        for message_id in failed_user_message_ids:
            if await self._retry_delete_message(bot, chat_id, message_id):
                continue
            retry_failed_user_message_ids.append(message_id)
        failed_user_message_ids = retry_failed_user_message_ids

        if last_question_message_id and (
            last_question_message_id not in previous_message_ids
            and last_question_message_id not in previous_user_message_ids
        ):
            try:
                await bot.delete_message(
                    chat_id=chat_id, message_id=last_question_message_id
                )
            except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
                self._logger.info(
                    "last_question_cleanup_failed",
                    extra={
                        "user_id": user_id,
                        "screen_id": state.screen_id,
                        "message_id": last_question_message_id,
                        "error": str(exc),
                    },
                )
                await self._try_edit_placeholder(
                    bot, chat_id, last_question_message_id, user_id, state.screen_id
                )
            self._store.clear_last_question_message_id(user_id)

        if previous_message_ids:
            self._store.clear_message_ids(user_id)
        if previous_user_message_ids:
            if not failed_user_message_ids:
                self._store.clear_user_message_ids(user_id)
            else:
                for message_id in previous_user_message_ids:
                    if message_id in failed_user_message_ids:
                        continue
                    self._store.remove_user_message_id(user_id, message_id)
                self._logger.warning(
                    "user_message_cleanup_incomplete",
                    extra={
                        "user_id": user_id,
                        "screen_id": state.screen_id,
                        "failed_message_ids": failed_user_message_ids,
                    },
                )
        if (
            last_question_message_id
            and last_question_message_id in previous_message_ids
        ):
            self._store.clear_last_question_message_id(user_id)

        if failed_message_ids and previous_message_ids and not image_path:
            first_message_id = previous_message_ids[0]
            if await self._try_edit_screen(
                bot, chat_id, first_message_id, content, user_id, screen_id
            ):
                for message_id in failed_message_ids:
                    if message_id == first_message_id:
                        continue
                    await self._try_edit_placeholder(
                        bot, chat_id, message_id, user_id, screen_id
                    )
                self._record_transition_event(
                    user_id=user_id,
                    from_screen=from_screen,
                    to_screen=to_screen,
                    trigger_type=trigger_type,
                    trigger_value=trigger_value,
                    transition_status=ScreenTransitionStatus.SUCCESS,
                    metadata_json=safe_metadata,
                )
                self._record_funnel_events(
                    user_id=user_id,
                    from_screen=from_screen,
                    to_screen=to_screen,
                    trigger_type=trigger_type,
                    trigger_value=trigger_value,
                    transition_status=ScreenTransitionStatus.SUCCESS,
                    metadata_json=safe_metadata,
                )
                return True
        for message_id in failed_message_ids:
            await self._try_edit_placeholder(
                bot, chat_id, message_id, user_id, screen_id
            )

        message_ids: list[int] = []
        image_sent = False
        send_text_after_image = False
        if image_path:
            caption = "\n\n".join(
                message for message in content.messages if message
            ).strip()
            if len(caption) > self._telegram_caption_limit:
                send_text_after_image = True
                caption = ""
            sent_photo = await self._send_photo_with_fallback(
                bot=bot,
                chat_id=chat_id,
                image_path=image_path,
                caption=caption or None,
                keyboard=None if send_text_after_image else content.keyboard,
                parse_mode=content.parse_mode if caption else None,
                user_id=user_id,
                screen_id=screen_id,
            )
            if sent_photo:
                message_ids.append(sent_photo.message_id)
                delivered = True
                image_sent = True
        if not image_path or not image_sent or send_text_after_image:
            expanded_messages: list[str] = []
            for message in content.messages:
                expanded_messages.extend(self._split_message(message))
            for index, message in enumerate(expanded_messages):
                reply_markup = (
                    content.keyboard if index == len(expanded_messages) - 1 else None
                )
                sent = await self._send_message_with_fallback(
                    bot=bot,
                    chat_id=chat_id,
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode=content.parse_mode,
                    user_id=user_id,
                    screen_id=screen_id,
                )
                if sent:
                    message_ids.append(sent.message_id)
                    delivered = True

        if message_ids:
            self._store.update_screen(user_id, screen_id, message_ids)
            delivered = True
        if delivered and screen_id in self._critical_screens:
            now_iso = datetime.now(timezone.utc).isoformat()
            self._store.update_data(
                user_id,
                last_critical_screen_id=screen_id,
                last_critical_stage=self._critical_screens.get(screen_id),
                last_critical_step_at=now_iso,
                last_critical_chat_id=chat_id,
            )
        if pdf_notice_required:
            try:
                sent_notice = await bot.send_message(
                    chat_id=chat_id,
                    text="Отчёт сохранён в личном кабинете.",
                )
                self._store.add_screen_message_id(user_id, sent_notice.message_id)
            except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
                self._logger.info(
                    "pdf_notice_send_failed",
                    extra={
                        "user_id": user_id,
                        "screen_id": screen_id,
                        "error": str(exc),
                    },
                )
        transition_status = (
            ScreenTransitionStatus.SUCCESS
            if delivered
            else ScreenTransitionStatus.BLOCKED
        )
        if not delivered:
            safe_metadata.setdefault("reason", "screen_delivery_blocked")
        self._record_transition_event(
            user_id=user_id,
            from_screen=from_screen,
            to_screen=to_screen,
            trigger_type=trigger_type,
            trigger_value=trigger_value,
            transition_status=transition_status,
            metadata_json=safe_metadata,
        )
        self._record_funnel_events(
            user_id=user_id,
            from_screen=from_screen,
            to_screen=to_screen,
            trigger_type=trigger_type,
            trigger_value=trigger_value,
            transition_status=transition_status,
            metadata_json=safe_metadata,
        )
        return delivered

    async def _retry_delete_message(
        self,
        bot: Bot,
        chat_id: int,
        message_id: int,
        *,
        attempts: int = 3,
        delay_seconds: float = 0.35,
    ) -> bool:
        for attempt in range(attempts):
            try:
                await asyncio.sleep(delay_seconds * (attempt + 1))
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
                return True
            except (TelegramBadRequest, TelegramForbiddenError, Exception):
                continue
        return False

    def _record_transition_event(
        self,
        *,
        user_id: int,
        from_screen: str | None,
        to_screen: str,
        trigger_type: ScreenTransitionTriggerType | str | None,
        trigger_value: str | None,
        transition_status: ScreenTransitionStatus | str | None,
        metadata_json: dict[str, Any] | None = None,
    ) -> None:
        state_data = self._store.get_state(user_id).data
        safe_metadata = self._enrich_metadata_with_tariff(
            metadata_json=metadata_json,
            state_data=state_data,
        )
        try:
            with get_session() as session:
                event = ScreenTransitionEvent.build_fail_safe(
                    telegram_user_id=user_id,
                    from_screen_id=from_screen,
                    to_screen_id=to_screen,
                    trigger_type=trigger_type,
                    trigger_value=trigger_value,
                    transition_status=transition_status,
                    metadata_json=safe_metadata,
                )
                session.add(event)
                session.flush()
        except Exception as exc:
            self._logger.warning(
                "screen_transition_event_store_failed",
                extra={
                    "user_id": user_id,
                    "from_screen": from_screen,
                    "to_screen": to_screen,
                    "error": str(exc),
                },
            )

    def _record_funnel_events(
        self,
        *,
        user_id: int,
        from_screen: str | None,
        to_screen: str,
        trigger_type: ScreenTransitionTriggerType | str | None,
        trigger_value: str | None,
        transition_status: ScreenTransitionStatus | str | None,
        metadata_json: dict[str, Any] | None,
    ) -> None:
        state_data = self._store.get_state(user_id).data
        safe_metadata = self._enrich_metadata_with_tariff(
            metadata_json=metadata_json,
            state_data=state_data,
        )
        if from_screen is None and to_screen == "S1":
            safe_metadata.setdefault("reason", "funnel_entry")
            self._record_transition_event(
                user_id=user_id,
                from_screen=from_screen,
                to_screen=to_screen,
                trigger_type=trigger_type,
                trigger_value=trigger_value,
                transition_status=transition_status,
                metadata_json=safe_metadata,
            )
            return

        if to_screen == "S7" and transition_status == ScreenTransitionStatus.SUCCESS:
            safe_metadata.setdefault("reason", "funnel_exit_report_completed")
            self._record_transition_event(
                user_id=user_id,
                from_screen=from_screen,
                to_screen=to_screen,
                trigger_type=trigger_type,
                trigger_value=trigger_value,
                transition_status=transition_status,
                metadata_json=safe_metadata,
            )
            return

        reason = str((safe_metadata or {}).get("reason") or "")
        if "timeout" in reason.lower():
            safe_metadata.setdefault("reason", "funnel_exit_timeout")
            self._record_transition_event(
                user_id=user_id,
                from_screen=from_screen,
                to_screen=to_screen,
                trigger_type=trigger_type,
                trigger_value=trigger_value,
                transition_status=ScreenTransitionStatus.BLOCKED,
                metadata_json=safe_metadata,
            )

    async def _try_edit_placeholder(
        self,
        bot: Bot,
        chat_id: int,
        message_id: int,
        user_id: int,
        screen_id: str | None,
    ) -> None:
        placeholder = "Экран обновлён."
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=placeholder,
                reply_markup=None,
            )
        except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
            try:
                await bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=placeholder,
                    reply_markup=None,
                )
            except (
                TelegramBadRequest,
                TelegramForbiddenError,
                Exception,
            ) as caption_exc:
                self._logger.info(
                    "screen_placeholder_edit_failed",
                    extra={
                        "user_id": user_id,
                        "screen_id": screen_id,
                        "message_id": message_id,
                        "error": str(caption_exc),
                    },
                )

    async def _try_edit_screen(
        self,
        bot: Bot,
        chat_id: int,
        message_id: int,
        content: ScreenContent,
        user_id: int,
        screen_id: str,
    ) -> bool:
        if len(content.messages) != 1:
            return False
        message = content.messages[0]
        if len(message) > self._telegram_message_limit:
            return False
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=message,
                reply_markup=content.keyboard,
                parse_mode=content.parse_mode,
            )
        except TelegramBadRequest:
            if content.parse_mode:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=message,
                        reply_markup=content.keyboard,
                        parse_mode=None,
                    )
                except (
                    TelegramBadRequest,
                    TelegramForbiddenError,
                    Exception,
                ) as retry_exc:
                    self._logger.info(
                        "screen_edit_failed",
                        extra={
                            "user_id": user_id,
                            "screen_id": screen_id,
                            "message_id": message_id,
                            "error": str(retry_exc),
                        },
                    )
                    return False
            else:
                self._logger.info(
                    "screen_edit_failed",
                    extra={
                        "user_id": user_id,
                        "screen_id": screen_id,
                        "message_id": message_id,
                        "error": "bad_request",
                    },
                )
                return False
        except (TelegramForbiddenError, Exception) as exc:
            self._logger.info(
                "screen_edit_failed",
                extra={
                    "user_id": user_id,
                    "screen_id": screen_id,
                    "message_id": message_id,
                    "error": str(exc),
                },
            )
            return False

        self._store.update_screen(user_id, screen_id, [message_id])
        return True

    def update_state(self, user_id: int, **kwargs: Any) -> ScreenState:
        return self._store.update_data(user_id, **kwargs)

    def get_state(self, user_id: int) -> ScreenState:
        return self._store.get_state(user_id)

    def _enrich_metadata_with_tariff(
        self,
        *,
        metadata_json: dict[str, Any] | None,
        state_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        safe_metadata = dict(metadata_json or {})
        if safe_metadata.get("tariff"):
            return safe_metadata
        selected_tariff = (state_data or {}).get("selected_tariff")
        if selected_tariff:
            safe_metadata["tariff"] = selected_tariff
        return safe_metadata


    def record_transition_event_safe(
        self,
        *,
        user_id: int,
        from_screen: str | None,
        to_screen: str,
        trigger_type: ScreenTransitionTriggerType | str | None,
        trigger_value: str | None,
        transition_status: ScreenTransitionStatus | str | None,
        metadata_json: dict[str, Any] | None = None,
    ) -> None:
        self._record_transition_event(
            user_id=user_id,
            from_screen=from_screen,
            to_screen=to_screen,
            trigger_type=trigger_type,
            trigger_value=trigger_value,
            transition_status=transition_status,
            metadata_json=metadata_json,
        )

    def add_screen_message_id(self, user_id: int, message_id: int) -> ScreenState:
        return self._store.add_screen_message_id(user_id, message_id)

    def add_user_message_id(self, user_id: int, message_id: int) -> ScreenState:
        return self._store.add_user_message_id(user_id, message_id)

    def add_pdf_message_id(self, user_id: int, message_id: int) -> ScreenState:
        return self._store.add_pdf_message_id(user_id, message_id)

    def update_last_question_message_id(
        self, user_id: int, message_id: int | None
    ) -> ScreenState:
        return self._store.update_last_question_message_id(user_id, message_id)

    async def delete_last_question_message(
        self, bot: Bot, chat_id: int, user_id: int
    ) -> None:
        state = self._store.get_state(user_id)
        last_message_id = state.last_question_message_id
        if not last_message_id:
            return
        try:
            await bot.delete_message(chat_id=chat_id, message_id=last_message_id)
        except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
            self._logger.info(
                "last_question_cleanup_failed",
                extra={
                    "user_id": user_id,
                    "screen_id": state.screen_id,
                    "message_id": last_message_id,
                    "error": str(exc),
                },
            )
            await self._try_edit_placeholder(
                bot, chat_id, last_message_id, user_id, state.screen_id
            )
        self._store.clear_last_question_message_id(user_id)

    async def clear_current_screen_inline_keyboards(
        self,
        bot: Bot,
        chat_id: int,
        user_id: int,
        cleanup_mode: CleanupMode = "remove_keyboard_only",
    ) -> None:
        state = self._store.get_state(user_id)
        if cleanup_mode == "delete_messages":
            for message_id in list(state.message_ids):
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=message_id)
                except (TelegramBadRequest, TelegramForbiddenError, Exception):
                    continue
            for message_id in list(state.user_message_ids):
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=message_id)
                except (TelegramBadRequest, TelegramForbiddenError, Exception):
                    continue
            self._store.clear_message_ids(user_id)
            self._store.clear_user_message_ids(user_id)
            return

        for message_id in list(state.message_ids):
            try:
                await bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=None,
                )
            except (TelegramBadRequest, TelegramForbiddenError, Exception):
                continue

    async def enter_text_input_mode(
        self,
        *,
        bot: Bot,
        chat_id: int,
        user_id: int,
        preserve_last_question: bool = False,
        cleanup_mode: CleanupMode = "remove_keyboard_only",
    ) -> None:
        if not preserve_last_question:
            await self.delete_last_question_message(
                bot=bot,
                chat_id=chat_id,
                user_id=user_id,
            )
        await self.clear_current_screen_inline_keyboards(
            bot=bot,
            chat_id=chat_id,
            user_id=user_id,
            cleanup_mode=cleanup_mode,
        )

    async def send_ephemeral_message(
        self,
        message: Message,
        text: str,
        user_id: int | None = None,
        delete_delay_seconds: float = 0,
        **kwargs: Any,
    ) -> None:
        if user_id is None:
            if not message.from_user:
                return
            user_id = message.from_user.id
        sent = await message.answer(text, **kwargs)
        self._store.add_screen_message_id(user_id, sent.message_id)
        reply_markup = kwargs.get("reply_markup")
        if reply_markup is None:
            asyncio.create_task(
                self._delete_screen_message_with_delay(
                    bot=message.bot,
                    chat_id=message.chat.id,
                    user_id=user_id,
                    message_id=sent.message_id,
                    delay_seconds=delete_delay_seconds,
                )
            )

    async def _delete_screen_message_with_delay(
        self,
        *,
        bot: Bot,
        chat_id: int,
        user_id: int,
        message_id: int,
        delay_seconds: float,
    ) -> None:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        await self.delete_screen_message(
            bot=bot,
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
        )

    async def delete_user_message(
        self,
        *,
        bot: Bot,
        chat_id: int,
        user_id: int,
        message_id: int,
    ) -> None:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
            self._logger.info(
                "user_message_cleanup_failed",
                extra={
                    "user_id": user_id,
                    "screen_id": self._store.get_state(user_id).screen_id,
                    "message_id": message_id,
                    "error": str(exc),
                },
            )
            self._store.remove_user_message_id(user_id, message_id)
            return
        self._store.remove_user_message_id(user_id, message_id)

    async def delete_screen_message(
        self,
        *,
        bot: Bot,
        chat_id: int,
        user_id: int,
        message_id: int,
    ) -> None:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
            self._logger.info(
                "screen_cleanup_failed",
                extra={
                    "user_id": user_id,
                    "screen_id": self._store.get_state(user_id).screen_id,
                    "message_id": message_id,
                    "error": str(exc),
                },
            )
            await self._try_edit_placeholder(
                bot,
                chat_id,
                message_id,
                user_id,
                self._store.get_state(user_id).screen_id,
            )
            self._store.remove_screen_message_id(user_id, message_id)
            return
        self._store.remove_screen_message_id(user_id, message_id)

    def clear_state(self, user_id: int) -> None:
        self._store.clear_state(user_id)

    def _split_message(self, message: str) -> list[str]:
        if not message:
            return [""]
        limit = self._telegram_message_limit
        if len(message) <= limit:
            return [message]
        chunks: list[str] = []
        start = 0
        length = len(message)
        while start < length:
            end = min(start + limit, length)
            split_at = message.rfind("\n", start, end)
            if split_at == -1 or split_at <= start:
                split_at = message.rfind(" ", start, end)
            if split_at == -1 or split_at <= start:
                split_at = end
            chunk = message[start:split_at].strip()
            if chunk:
                chunks.append(chunk)
            start = split_at
        if not chunks:
            chunks.append(message[:limit])
        return chunks

    async def _send_message_with_fallback(
        self,
        *,
        bot: Bot,
        chat_id: int,
        text: str,
        reply_markup,
        parse_mode: str | None,
        user_id: int,
        screen_id: str,
    ) -> Message | None:
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except TelegramBadRequest:
            if parse_mode:
                try:
                    return await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=None,
                    )
                except (
                    TelegramBadRequest,
                    TelegramForbiddenError,
                    Exception,
                ) as retry_exc:
                    self._logger.info(
                        "screen_send_failed",
                        extra={
                            "user_id": user_id,
                            "screen_id": screen_id,
                            "error": str(retry_exc),
                        },
                    )
                    return None
        except (TelegramForbiddenError, Exception) as exc:
            self._logger.info(
                "screen_send_failed",
                extra={
                    "user_id": user_id,
                    "screen_id": screen_id,
                    "error": str(exc),
                },
            )
            return None
        return None

    async def _send_photo_with_fallback(
        self,
        *,
        bot: Bot,
        chat_id: int,
        image_path,
        caption: str | None,
        keyboard,
        parse_mode: str | None,
        user_id: int,
        screen_id: str,
    ) -> Message | None:
        try:
            return await bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(image_path),
                caption=caption,
                reply_markup=keyboard,
                parse_mode=parse_mode if caption else None,
            )
        except TelegramBadRequest:
            if parse_mode:
                try:
                    return await bot.send_photo(
                        chat_id=chat_id,
                        photo=FSInputFile(image_path),
                        caption=caption,
                        reply_markup=keyboard,
                        parse_mode=None,
                    )
                except (
                    TelegramBadRequest,
                    TelegramForbiddenError,
                    Exception,
                ) as retry_exc:
                    self._logger.info(
                        "screen_image_send_failed",
                        extra={
                            "user_id": user_id,
                            "screen_id": screen_id,
                            "image_path": str(image_path),
                            "error": str(retry_exc),
                        },
                    )
                    return None
        except (TelegramForbiddenError, Exception) as exc:
            self._logger.info(
                "screen_image_send_failed",
                extra={
                    "user_id": user_id,
                    "screen_id": screen_id,
                    "image_path": str(image_path),
                    "error": str(exc),
                },
            )
            return None
        return None


screen_manager = ScreenManager()
