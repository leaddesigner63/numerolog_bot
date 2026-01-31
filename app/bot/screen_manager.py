from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.bot.screens import SCREEN_REGISTRY, ScreenContent


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
            self._states[user_id] = ScreenState()
        return self._states[user_id]

    def update_data(self, user_id: int, **kwargs: Any) -> ScreenState:
        state = self.get_state(user_id)
        state.data.update(kwargs)
        return state


class ScreenManager:
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

        delete_failed = False
        for message_id in list(state.message_ids):
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except (TelegramBadRequest, TelegramForbiddenError) as exc:
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

        if delete_failed and state.message_ids:
            first_message_id = state.message_ids[0]
            if await self._try_edit_screen(bot, chat_id, first_message_id, content, user_id, screen_id):
                return

        message_ids: list[int] = []
        for index, message in enumerate(content.messages):
            reply_markup = content.keyboard if index == len(content.messages) - 1 else None
            sent = await bot.send_message(chat_id=chat_id, text=message, reply_markup=reply_markup)
            message_ids.append(sent.message_id)

        state.screen_id = screen_id
        state.message_ids = message_ids

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
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=content.messages[0],
                reply_markup=content.keyboard,
            )
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
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

        state = self._store.get_state(user_id)
        state.screen_id = screen_id
        state.message_ids = [message_id]
        return True

    def update_state(self, user_id: int, **kwargs: Any) -> ScreenState:
        return self._store.update_data(user_id, **kwargs)


screen_manager = ScreenManager()
