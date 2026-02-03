from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.bot.screens import SCREEN_REGISTRY, ScreenContent
from app.db.models import ScreenStateRecord
from app.db.session import get_session


@dataclass
class ScreenState:
    screen_id: str | None = None
    message_ids: list[int] = field(default_factory=list)
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

    def clear_message_ids(self, user_id: int) -> None:
        state = self.get_state(user_id)
        if not state.message_ids:
            return
        state.message_ids = []
        self._persist_state(user_id, state)

    def _load_state(self, user_id: int) -> ScreenState:
        with get_session() as session:
            record = session.get(ScreenStateRecord, user_id)
            if not record:
                return ScreenState()
            return ScreenState(
                screen_id=record.screen_id,
                message_ids=list(record.message_ids or []),
                data=dict(record.data or {}),
            )

    def _persist_state(self, user_id: int, state: ScreenState) -> None:
        with get_session() as session:
            record = session.get(ScreenStateRecord, user_id)
            if record:
                record.screen_id = state.screen_id
                record.message_ids = state.message_ids
                record.data = state.data
            else:
                record = ScreenStateRecord(
                    telegram_user_id=user_id,
                    screen_id=state.screen_id,
                    message_ids=state.message_ids,
                    data=state.data,
                )
                session.add(record)
            session.flush()


class ScreenManager:
    _telegram_message_limit = 4096

    def __init__(self, store: ScreenStateStore | None = None) -> None:
        self._store = store or ScreenStateStore()
        self._logger = logging.getLogger(__name__)

    def render_screen(self, screen_id: str, user_id: int, state: dict[str, Any]) -> ScreenContent:
        screen_fn = SCREEN_REGISTRY.get(screen_id)
        if not screen_fn:
            raise ValueError(f"Unknown screen id: {screen_id}")
        return screen_fn(state)

    async def show_screen(self, bot: Bot, chat_id: int, user_id: int, screen_id: str) -> None:
        state = self._store.get_state(user_id)
        content = self.render_screen(screen_id, user_id, state.data)

        previous_message_ids = list(state.message_ids)
        delete_failed = False
        for message_id in previous_message_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
                delete_failed = True
                self._logger.info(
                    "screen_cleanup_failed",
                    extra={
                        "user_id": user_id,
                        "screen_id": state.screen_id,
                        "message_id": message_id,
                        "error": str(exc),
                    },
                )

        if previous_message_ids:
            self._store.clear_message_ids(user_id)

        if delete_failed and previous_message_ids:
            first_message_id = previous_message_ids[0]
            if await self._try_edit_screen(bot, chat_id, first_message_id, content, user_id, screen_id):
                return

        expanded_messages: list[str] = []
        for message in content.messages:
            expanded_messages.extend(self._split_message(message))

        message_ids: list[int] = []
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
