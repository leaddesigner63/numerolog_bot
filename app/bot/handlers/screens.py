from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery

from app.bot.screen_manager import screen_manager


router = Router()


@router.callback_query()
async def handle_callbacks(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer()
        return

    if callback.data.startswith("screen:"):
        screen_id = callback.data.split("screen:")[-1]
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id=screen_id,
        )
        await callback.answer()
        return

    if callback.data.startswith("tariff:"):
        tariff = callback.data.split("tariff:")[-1]
        screen_manager.update_state(callback.from_user.id, selected_tariff=tariff)
        next_screen = "S4" if tariff == "T0" else "S2"
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id=next_screen,
        )
        await callback.answer()
        return

    if callback.data == "payment:paid":
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id="S4",
        )
        await callback.answer()
        return

    if callback.data == "profile:save":
        state = screen_manager.update_state(callback.from_user.id)
        next_screen = "S5" if state.data.get("selected_tariff") in {"T2", "T3"} else "S6"
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id=next_screen,
        )
        await callback.answer()
        return

    if callback.data == "questionnaire:done":
        await screen_manager.show_screen(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            screen_id="S6",
        )
        await callback.answer()
        return

    if callback.data == "report:pdf":
        await callback.message.answer("PDF будет доступен после генерации отчёта.")
        await callback.answer()
        return

    if callback.data == "feedback:send":
        await callback.message.answer("Сообщение будет отправлено в группу после запуска потока обратной связи.")
        await callback.answer()
        return

    await callback.answer()
