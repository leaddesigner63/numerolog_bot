from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.config import settings
from app.core.gemini_image_service import GeminiImageError, gemini_image_service


router = Router()


class FillScreenImagesState(StatesGroup):
    waiting_prompt = State()


@dataclass
class ScreenImageTarget:
    screen_key: str
    directory: Path
    description: str


@dataclass
class FillScreenImagesSession:
    user_id: int
    chat_id: int
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    progress_message_id: int | None = None
    report_message_id: int | None = None
    report_message_ids: list[int] = field(default_factory=list)
    cleanup_message_ids: list[int] = field(default_factory=list)
    cleanup_user_message_ids: list[int] = field(default_factory=list)


ACTIVE_FILL_SESSIONS: dict[int, FillScreenImagesSession] = {}
REPORT_TTL_SECONDS = 60


def _stop_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Остановить генерацию", callback_data="fill_images:stop")]
        ]
    )


def _close_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Закрыть отчёт", callback_data="fill_images:close")]]
    )


def _extension_for_mime(mime_type: str) -> str:
    if "png" in mime_type:
        return ".png"
    if "jpeg" in mime_type or "jpg" in mime_type:
        return ".jpg"
    if "webp" in mime_type:
        return ".webp"
    return ".png"


def _collect_targets(base_dir: Path) -> list[ScreenImageTarget]:
    targets: list[ScreenImageTarget] = []
    for item in sorted(base_dir.iterdir()):
        if item.name.startswith(".") or not item.is_dir():
            continue
        description_path = item / "description.txt"
        description = ""
        if description_path.exists():
            description = description_path.read_text(encoding="utf-8")
        targets.append(
            ScreenImageTarget(
                screen_key=item.name,
                directory=item,
                description=description,
            )
        )
    return targets


def _split_message(text: str, *, max_length: int = 4096) -> list[str]:
    if not text:
        return [""]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= max_length:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(line) <= max_length:
            current = line
            continue
        for idx in range(0, len(line), max_length):
            chunks.append(line[idx : idx + max_length])
    if current:
        chunks.append(current)
    return chunks


async def _safe_delete_message(bot: Bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        return


async def _cleanup_messages(bot: Bot, chat_id: int, message_ids: list[int]) -> None:
    for message_id in message_ids:
        await _safe_delete_message(bot, chat_id, message_id)


def _build_report(
    *,
    started_at: datetime,
    finished_at: datetime,
    total: int,
    completed: int,
    failed: int,
    stopped: bool,
    details: list[str],
) -> str:
    status_line = "Остановлено пользователем." if stopped else "Готово."
    duration_seconds = int((finished_at - started_at).total_seconds())
    summary = (
        f"{status_line}\n"
        f"Экранов всего: {total}\n"
        f"Успешно: {completed}\n"
        f"Ошибки: {failed}\n"
        f"Длительность: {duration_seconds} сек.\n"
        f"Сообщение будет удалено автоматически через {REPORT_TTL_SECONDS} сек."
    )
    if not details:
        return summary
    detail_block = "\n".join(details)
    return f"{summary}\n\nДетализация:\n{detail_block}"


async def _run_fill_screen_images(
    *,
    bot: Bot,
    session: FillScreenImagesSession,
    prompt: str,
) -> None:
    started_at = datetime.now(timezone.utc)
    details: list[str] = []
    completed = 0
    failed = 0
    stopped = False

    base_dir_value = settings.screen_images_dir
    if not base_dir_value:
        details.append("❌ Папка для изображений не задана (SCREEN_IMAGES_DIR).")
        finished_at = datetime.now(timezone.utc)
        report_text = _build_report(
            started_at=started_at,
            finished_at=finished_at,
            total=0,
            completed=0,
            failed=1,
            stopped=False,
            details=details,
        )
        await _send_report(bot, session, report_text)
        return

    base_dir = Path(base_dir_value)
    if not base_dir.exists():
        details.append(f"❌ Папка для изображений не найдена: {base_dir_value}")
        finished_at = datetime.now(timezone.utc)
        report_text = _build_report(
            started_at=started_at,
            finished_at=finished_at,
            total=0,
            completed=0,
            failed=1,
            stopped=False,
            details=details,
        )
        await _send_report(bot, session, report_text)
        return

    targets = _collect_targets(base_dir)
    total = len(targets)
    if total == 0:
        details.append("❌ В папке экранов нет каталогов для генерации.")
        finished_at = datetime.now(timezone.utc)
        report_text = _build_report(
            started_at=started_at,
            finished_at=finished_at,
            total=0,
            completed=0,
            failed=1,
            stopped=False,
            details=details,
        )
        await _send_report(bot, session, report_text)
        return

    for index, target in enumerate(targets, start=1):
        if session.cancel_event.is_set():
            stopped = True
            break
        await _update_progress(
            bot,
            session,
            f"Генерация изображений: {index}/{total}\nЭкран: {target.screen_key}",
        )
        screen_prompt = f"{prompt}\n\n{target.description}" if target.description else prompt
        try:
            result = gemini_image_service.generate_image(screen_prompt)
            extension = _extension_for_mime(result.mime_type)
            filename = f"generated_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{index}{extension}"
            target.directory.mkdir(parents=True, exist_ok=True)
            image_path = target.directory / filename
            image_path.write_bytes(result.image_bytes)
            completed += 1
            details.append(f"✅ {target.screen_key}: {image_path.as_posix()}")
        except GeminiImageError as exc:
            failed += 1
            if exc.category == "rate_limited":
                retry_hint = ""
                if exc.retry_after:
                    retry_hint = f" (повторите через {int(exc.retry_after)} сек.)"
                details.append(f"❌ {target.screen_key}: превышен лимит Gemini{retry_hint}.")
                stopped = True
                break
            details.append(f"❌ {target.screen_key}: {exc}")
            if exc.category in {"missing_api_key", "missing_model"}:
                break
        except Exception as exc:
            failed += 1
            details.append(f"❌ {target.screen_key}: {exc}")

    finished_at = datetime.now(timezone.utc)
    report_text = _build_report(
        started_at=started_at,
        finished_at=finished_at,
        total=total,
        completed=completed,
        failed=failed,
        stopped=stopped,
        details=details,
    )
    await _send_report(bot, session, report_text)


async def _update_progress(bot: Bot, session: FillScreenImagesSession, text: str) -> None:
    if not session.progress_message_id:
        return
    try:
        await bot.edit_message_text(
            chat_id=session.chat_id,
            message_id=session.progress_message_id,
            text=text,
            reply_markup=_stop_keyboard(),
        )
    except Exception:
        return


async def _send_report(bot: Bot, session: FillScreenImagesSession, report_text: str) -> None:
    await _cleanup_messages(bot, session.chat_id, session.cleanup_message_ids)
    await _cleanup_messages(bot, session.chat_id, session.cleanup_user_message_ids)
    if session.progress_message_id:
        await _safe_delete_message(bot, session.chat_id, session.progress_message_id)

    try:
        parts = _split_message(report_text)
        for index, part in enumerate(parts):
            sent = await bot.send_message(
                chat_id=session.chat_id,
                text=part,
                reply_markup=_close_keyboard() if index == len(parts) - 1 else None,
            )
            session.report_message_ids.append(sent.message_id)
            session.report_message_id = sent.message_id
        asyncio.create_task(
            _auto_delete_report(
                bot=bot,
                chat_id=session.chat_id,
                message_ids=session.report_message_ids,
                user_id=session.user_id,
            )
        )
    finally:
        if session.user_id not in ACTIVE_FILL_SESSIONS:
            ACTIVE_FILL_SESSIONS[session.user_id] = session


async def _auto_delete_report(
    *, bot: Bot, chat_id: int, message_ids: list[int], user_id: int
) -> None:
    await asyncio.sleep(REPORT_TTL_SECONDS)
    await _cleanup_messages(bot, chat_id, message_ids)
    ACTIVE_FILL_SESSIONS.pop(user_id, None)


@router.message(Command("fill_screen_images"))
async def handle_fill_screen_images(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    session = ACTIVE_FILL_SESSIONS.get(user_id)
    if session and session.task and not session.task.done():
        sent = await message.answer(
            "Генерация уже идёт. Можно остановить текущую задачу.",
            reply_markup=_stop_keyboard(),
        )
        session.cleanup_message_ids.append(sent.message_id)
        return

    await state.set_state(FillScreenImagesState.waiting_prompt)
    sent = await message.answer("Отправьте универсальный промпт для генерации изображений.")
    await state.update_data(
        command_message_id=message.message_id,
        prompt_request_message_id=sent.message_id,
    )
    await _safe_delete_message(message.bot, message.chat.id, message.message_id)


@router.message(FillScreenImagesState.waiting_prompt)
async def handle_fill_screen_images_prompt(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    await state.clear()

    command_message_id = data.get("command_message_id")
    prompt_request_message_id = data.get("prompt_request_message_id")
    prompt = message.text or message.caption or ""

    session = FillScreenImagesSession(user_id=message.from_user.id, chat_id=message.chat.id)
    session.cleanup_user_message_ids.extend(
        [message.message_id, command_message_id] if command_message_id else [message.message_id]
    )
    if prompt_request_message_id:
        session.cleanup_message_ids.append(prompt_request_message_id)

    progress = await message.answer(
        "Запускаю генерацию изображений по экранам…",
        reply_markup=_stop_keyboard(),
    )
    session.progress_message_id = progress.message_id
    ACTIVE_FILL_SESSIONS[message.from_user.id] = session
    session.task = asyncio.create_task(
        _run_fill_screen_images(bot=message.bot, session=session, prompt=prompt)
    )
    await _safe_delete_message(message.bot, message.chat.id, message.message_id)


@router.callback_query(F.data == "fill_images:stop")
async def handle_fill_screen_images_stop(callback: CallbackQuery) -> None:
    if not callback.from_user:
        return
    session = ACTIVE_FILL_SESSIONS.get(callback.from_user.id)
    if session:
        session.cancel_event.set()
        await _update_progress(
            callback.message.bot,
            session,
            "Останавливаю генерацию…",
        )
    try:
        await callback.answer("Останавливаю…")
    except Exception:
        return


@router.callback_query(F.data == "fill_images:close")
async def handle_fill_screen_images_close(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    session = ACTIVE_FILL_SESSIONS.get(callback.from_user.id)
    if session:
        await _cleanup_messages(callback.message.bot, callback.message.chat.id, session.report_message_ids)
        ACTIVE_FILL_SESSIONS.pop(callback.from_user.id, None)
    else:
        await _safe_delete_message(
            callback.message.bot, callback.message.chat.id, callback.message.message_id
        )
    try:
        await callback.answer("Отчёт удалён.")
    except Exception:
        return
