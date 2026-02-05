from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile, Message

from app.bot.screen_images import resolve_screen_image_path
from app.bot.screens import SCREEN_REGISTRY, ScreenContent
from app.db.models import ScreenStateRecord
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

    def update_screen(self, user_id: int, screen_id: str, message_ids: list[int]) -> ScreenState:
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

    def add_user_message_id(self, user_id: int, message_id: int) -> ScreenState:
        state = self.get_state(user_id)
        state.user_message_ids.append(message_id)
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
    _telegram_message_limit = 4096
    _telegram_caption_limit = 1024

    def __init__(self, store: ScreenStateStore | None = None) -> None:
        self._store = store or ScreenStateStore()
        self._logger = logging.getLogger(__name__)

    def render_screen(self, screen_id: str, user_id: int, state: dict[str, Any]) -> ScreenContent:
        screen_fn = SCREEN_REGISTRY.get(screen_id)
        if not screen_fn:
            raise ValueError(f"Unknown screen id: {screen_id}")
        return screen_fn(state)

    async def show_screen(self, bot: Bot, chat_id: int, user_id: int, screen_id: str) -> bool:
        state = self._store.get_state(user_id)
        content = self.render_screen(screen_id, user_id, state.data)
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

        for message_id in previous_user_message_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
                self._logger.info(
                    "user_message_cleanup_failed",
                    extra={
                        "user_id": user_id,
                        "screen_id": state.screen_id,
                        "message_id": message_id,
                        "error": str(exc),
                    },
                )

        if last_question_message_id and (
            last_question_message_id not in previous_message_ids
            and last_question_message_id not in previous_user_message_ids
        ):
            try:
                await bot.delete_message(chat_id=chat_id, message_id=last_question_message_id)
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
            self._store.clear_user_message_ids(user_id)
        if last_question_message_id and last_question_message_id in previous_message_ids:
            self._store.clear_last_question_message_id(user_id)

        if failed_message_ids and previous_message_ids and not image_path:
            first_message_id = previous_message_ids[0]
            if await self._try_edit_screen(bot, chat_id, first_message_id, content, user_id, screen_id):
                for message_id in failed_message_ids:
                    if message_id == first_message_id:
                        continue
                    await self._try_edit_placeholder(bot, chat_id, message_id, user_id, screen_id)
                return True
            for message_id in failed_message_ids:
                await self._try_edit_placeholder(bot, chat_id, message_id, user_id, screen_id)

        message_ids: list[int] = []
        image_sent = False
        if image_path:
            try:
                caption = "\n\n".join(message for message in content.messages if message).strip()
                if len(caption) > self._telegram_caption_limit:
                    truncated = caption[: self._telegram_caption_limit - 1].rstrip()
                    caption = f"{truncated}…"
                sent_photo = await bot.send_photo(
                    chat_id=chat_id,
                    photo=FSInputFile(image_path),
                    caption=caption or None,
                    reply_markup=content.keyboard,
                    parse_mode=content.parse_mode if caption else None,
                )
                message_ids.append(sent_photo.message_id)
                delivered = True
                image_sent = True
            except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
                self._logger.info(
                    "screen_image_send_failed",
                    extra={
                        "user_id": user_id,
                        "screen_id": screen_id,
                        "image_path": str(image_path),
                        "error": str(exc),
                    },
                )
        if not image_path or not image_sent:
            expanded_messages: list[str] = []
            for message in content.messages:
                expanded_messages.extend(self._split_message(message))
            for index, message in enumerate(expanded_messages):
                reply_markup = content.keyboard if index == len(expanded_messages) - 1 else None
                try:
                    sent = await bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        reply_markup=reply_markup,
                        parse_mode=content.parse_mode,
                    )
                    message_ids.append(sent.message_id)
                    delivered = True
                except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
                    self._logger.info(
                        "screen_send_failed",
                        extra={
                            "user_id": user_id,
                            "screen_id": screen_id,
                            "error": str(exc),
                        },
                    )

        if message_ids:
            self._store.update_screen(user_id, screen_id, message_ids)
            delivered = True
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
        return delivered

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
            self._logger.info(
                "screen_placeholder_edit_failed",
                extra={
                    "user_id": user_id,
                    "screen_id": screen_id,
                    "message_id": message_id,
                    "error": str(exc),
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
        except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
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

    async def send_ephemeral_message(
        self,
        message: Message,
        text: str,
        user_id: int | None = None,
        **kwargs: Any,
    ) -> None:
        if user_id is None:
            if not message.from_user:
                return
            user_id = message.from_user.id
        sent = await message.answer(text, **kwargs)
        self._store.add_screen_message_id(user_id, sent.message_id)

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


screen_manager = ScreenManager()
