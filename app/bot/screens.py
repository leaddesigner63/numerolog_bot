from __future__ import annotations

import logging
import re
from datetime import datetime
from dataclasses import dataclass
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards import enforce_long_button_rows
from app.bot.questionnaire.config import load_questionnaire_config
from app.core.config import settings
from app.core.report_text_pipeline import build_canonical_report_text
from app.core.tariff_labels import tariff_button_title


@dataclass(frozen=True)
class ScreenContent:
    messages: list[str]
    keyboard: InlineKeyboardMarkup | None = None
    parse_mode: str | None = None
    image_path: str | None = None


# Единый справочник тарифов (чтобы UI не расходился с логикой оплаты)
def _tariff_price_from_settings(tariff: str) -> int:
    prices = getattr(settings, "tariff_prices_rub", {}) or {}
    raw_value = prices.get(tariff)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0


TARIFF_META: dict[str, dict[str, Any]] = {
    "T0": {
        "title": "Твоё новое начало",
        "price": _tariff_price_from_settings("T0"),
        "bullets": [
            "структура полного отчёта (витрина)",
            "краткое резюме (5–7 пунктов)",
            "сильные стороны и зоны роста (сжато)",
            "ориентиры по сферам",
            "короткая нейтральная ретроспектива (2–3 предложения)",
        ],
        "note": "Доступно не чаще 1 раза в месяц.",
    },
    "T1": {
        "title": "В чём твоя сила?",
        "price": _tariff_price_from_settings("T1"),
        "bullets": [
            "Результат: персональная карта сильных сторон и векторов роста.",
            "Польза: понятно, на что опираться в решениях и развитии.",
            "Для кого: для тех, кто хочет увидеть свой потенциал без догадок.",
        ],
        "details": (
            "Ты ярче, чем думаешь. ИИ уже видит твой потенциал и раскрывает предрасположенности, "
            "таланты и зоны роста. В итоге ты получаешь чёткое понимание своих сильных сторон и "
            "гипотезы, куда двигаться дальше."
        ),
        "note": None,
    },
    "T2": {
        "title": "Где твои деньги?",
        "price": _tariff_price_from_settings("T2"),
        "bullets": [
            "Результат: разбор денежных сценариев и точек роста дохода.",
            "Польза: фокус на действиях, которые усиливают финансовый трек.",
            "Для кого: для тех, кто хочет зарабатывать системнее и увереннее.",
        ],
        "details": (
            "Здесь ИИ копает глубже: анализирует тебя с упором на доход и моделирует сценарии будущего. "
            "Ты узнаешь, где спрятаны возможности роста дохода, какие повороты вероятны и как реализовать "
            "свои способности на полную."
        ),
        "note": None,
    },
    "T3": {
        "title": "Твой путь к себе!",
        "price": _tariff_price_from_settings("T3"),
        "bullets": [
            "Результат: персональный маршрут развития с приоритетами.",
            "Польза: меньше хаоса, больше ясности по шагам и срокам.",
            "Для кого: для тех, кто готов к системным изменениям в жизни.",
        ],
        "details": (
            "Если чувствуешь, что способен на большее, но не хватает структуры, этот тариф поможет. "
            "ИИ соберёт маршрут с конкретными шагами, сроками и рекомендациями: что, когда и как делать, "
            "чтобы раскрыть потенциал и двигаться к своим целям уверенно."
        ),
        "note": None,
    },
}


logger = logging.getLogger(__name__)
_BOT_MENTION_PREFIX_RE = re.compile(r"^\s*@\w+\s+")
_QUESTIONNAIRE_PREVIEW_LIMIT = 180


CTA_LABELS: dict[str, Any] = {
    "tariff_selection": "Выбрать тариф",
    "profile_input": "Заполнить данные",
    "questionnaire": "Заполнить анкету",
    "payment": {
        "before_payment_url": "Перейти к оплате",
        "with_payment_url": "Оплатить",
    },
}

SCREEN_SEPARATOR = "──────────"
EMOJI_STEP = "🔹"
EMOJI_BENEFIT = "✅"
EMOJI_ACTION = "👉"
EMOJI_WARNING = "⚠️"


def resolve_payment_mode(raw_mode: str | None) -> str:
    mode = str(raw_mode or "").strip().lower()
    if mode == "manual":
        return "manual"
    return "provider"


def get_payment_flow_context() -> dict[str, Any]:
    mode = resolve_payment_mode(getattr(settings, "payment_mode", None))
    manual_card_number = getattr(settings, "manual_payment_card_number", None)
    manual_recipient_name = getattr(settings, "manual_payment_recipient_name", None)
    manual_card_ready = bool(str(manual_card_number or "").strip())
    return {
        "mode": mode,
        "manual_card_number": manual_card_number,
        "manual_recipient_name": manual_recipient_name,
        "manual_card_ready": manual_card_ready,
    }


def _build_screen_header(title: str) -> str:
    return f"{EMOJI_STEP} {title.strip()}\n{SCREEN_SEPARATOR}"


def _build_bullets(items: list[str], emoji: str = EMOJI_BENEFIT) -> str:
    return "\n".join(f"{emoji} {item.strip()}" for item in items if item and item.strip())


def _build_cta_line(text: str, emoji: str = EMOJI_ACTION) -> str:
    return f"{emoji} {text.strip()}"


def _sanitize_report_text(report_text: str, *, tariff: str = "unknown") -> str:
    return build_canonical_report_text(report_text, tariff)


def _global_menu() -> list[list[InlineKeyboardButton]]:
    if not settings.global_menu_enabled:
        return []
    return [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Тарифы", "🧾"),
                callback_data="screen:S1",
            ),
            InlineKeyboardButton(
                text=_with_button_icons("Мои данные", "👤"),
                callback_data="screen:S4",
            ),
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Оферта/Условия", "📄"),
                callback_data="legal:offer",
            ),
            InlineKeyboardButton(
                text=_with_button_icons("Обратная связь", "💬"),
                callback_data="screen:S8",
            ),
        ],
    ]


def _build_keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in enforce_long_button_rows(rows):
        builder.row(*row)
    return builder.as_markup()


def _with_button_icons(text: str, icon: str) -> str:
    clean_text = text.strip()
    return f"{icon} {clean_text}"


def _format_tariff_label(tariff: str) -> str:
    return tariff_button_title(tariff, fallback=tariff)


def _with_screen_prefix(screen_id: str, text: str) -> str:
    if settings.screen_title_enabled:
        return f"{screen_id}: {text.lstrip()}"
    return text.lstrip()


def _build_text_progress_bar(progress: float, length: int = 12) -> str:
    safe_progress = min(max(progress, 0.0), 1.0)
    filled = int(round(safe_progress * length))
    empty = max(length - filled, 0)
    return "█" * filled + "░" * empty


def build_report_wait_message(
    remaining_seconds: int | None = None,
    frame: str = EMOJI_STEP,
    total_seconds: int | None = None,
    progress: float | None = None,
) -> str:
    base_text = "Генерируем отчёт… Пожалуйста, подождите."
    if remaining_seconds is None and progress is None:
        return _with_screen_prefix("S6", f"{frame} {base_text}")

    safe_total = total_seconds if isinstance(total_seconds, int) and total_seconds > 0 else None
    resolved_progress = progress
    if safe_total is not None:
        done = max(safe_total - max(remaining_seconds, 0), 0)
        resolved_progress = done / safe_total

    progress_line = ""
    if resolved_progress is not None:
        progress_bar = _build_text_progress_bar(resolved_progress)
        percent = int(round(resolved_progress * 100))
        progress_line = f"\nПрогресс: [{progress_bar}] {percent}%"

    remaining_line = ""
    if remaining_seconds is not None:
        remaining_line = f"\nОсталось: {remaining_seconds} сек."

    return _with_screen_prefix(
        "S6",
        f"{frame} {base_text}{progress_line}{remaining_line}",
    )


def build_payment_wait_message(frame: str = EMOJI_STEP) -> str:
    return _with_screen_prefix("S3", f"{frame} Платеж обрабатывается, пожалуйста подождите.")


def _common_disclaimer_short() -> str:
    return (
        "Материалы сервиса носят информационно-аналитический характер, не являются индивидуальной "
        "консультацией и не гарантируют конкретный результат."
    )


def _common_disclaimer_full() -> str:
    return (
        "Важно:\n"
        "• Сервис не является консультацией, прогнозом или рекомендацией к действию.\n"
        "• Все выводы носят аналитический и описательный характер.\n"
        "• Ответственность за решения остаётся за пользователем.\n"
        "• Сервис не гарантирует финансовых или иных результатов.\n"
    )


def _tariff_meta(tariff: str | None) -> dict[str, Any] | None:
    if not tariff:
        return None
    return TARIFF_META.get(tariff)


def _format_price(state: dict[str, Any], tariff: str) -> str:
    # Если заказ уже создан — показываем сумму из заказа (истина оплаты).
    order_amount = state.get("order_amount")
    order_currency = state.get("order_currency", "RUB")
    if order_amount:
        return f"{order_amount} {order_currency}"
    # Fallback — из справочника
    price = settings.tariff_prices_rub.get(tariff)
    if price is None:
        return ""
    return f"{price} RUB"


def _tariff_button_with_price(tariff: str) -> str:
    base_title = tariff_button_title(tariff, fallback=tariff)
    price = settings.tariff_prices_rub.get(tariff)
    try:
        price_value = int(price)
    except (TypeError, ValueError):
        return base_title
    return f"{base_title} — {price_value} ₽"


def screen_s0(_: dict[str, Any]) -> ScreenContent:
    bullets = [
        "Вы увидите сильные стороны и зоны роста по вашим данным.",
        "Получите понятную структуру полного отчёта до оплаты.",
        "Сразу поймёте формат и пользу следующего шага.",
    ]
    text = _with_screen_prefix(
        "S0",
        "\n".join(
            [
                _build_screen_header("Шаг 1. Как работает разбор"),
                _build_bullets(bullets),
                _build_cta_line("Нажмите «Далее», чтобы выбрать тариф."),
            ]
        ),
    )
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Далее", "➡️"),
                callback_data="screen:S1",
            )
        ],
        
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s1(_: dict[str, Any]) -> ScreenContent:
    bullets = [
        "Каждый тариф даёт разную глубину анализа и рекомендации.",
        "Можно начать с бесплатного варианта и оценить подход.",
        "Платные тарифы открывают расширенный персональный отчёт.",
    ]
    text = _with_screen_prefix(
        "S1",
        "\n".join(
            [
                _build_screen_header("Шаг 2. Выбор тарифа"),
                _build_bullets(bullets),
                _build_cta_line("Нажмите на тариф, который хотите получить сейчас."),
            ]
        ),
    )
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons(_tariff_button_with_price("T0"), "🌱"),
                callback_data="tariff:T0",
            ),
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons(_tariff_button_with_price("T1"), "💪"),
                callback_data="tariff:T1",
            ),
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons(_tariff_button_with_price("T2"), "💰"),
                callback_data="tariff:T2",
            ),
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons(_tariff_button_with_price("T3"), "🧭"),
                callback_data="tariff:T3",
            ),
        ],
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s2(state: dict[str, Any]) -> ScreenContent:
    """
    S2 выполняет две роли:
    - Если selected_tariff = T1/T2/T3: экран описания выбранного тарифа + переход к заполнению данных.
    - Если тариф не выбран: экран оферты/правил (доступен из меню).
    """
    selected_tariff_raw = state.get("selected_tariff")
    meta = _tariff_meta(selected_tariff_raw)

    # 1) Если нет тарифа — показываем оферту/правила
    if not meta or selected_tariff_raw not in {"T1", "T2", "T3"}:
        return screen_s2_legal(state)

    # 2) Тариф выбран (T1/T2/T3) — показываем описание тарифа
    bullets = meta.get("bullets") or []
    bullets_text = _build_bullets(bullets)

    note = meta.get("note")
    note_text = f"\n\n{EMOJI_WARNING} Примечание: {note}" if note else ""
    text = _with_screen_prefix(
        "S2",
        (
            f"{_build_screen_header(meta['title'])}\n"
            f"{bullets_text}"
            f"{note_text}\n\n"
            f"{_build_cta_line('Нажмите «Заполнить данные», чтобы продолжить.')}"
        ),
    )
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=_with_button_icons(CTA_LABELS["profile_input"], "➡️"),
                callback_data="screen:S4",
            ),
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Подробнее", "ℹ️"),
                callback_data="s2:details",
            ),
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Назад", "↩️"),
                callback_data="screen:S1",
            ),
        ],
    ]
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s2_details(state: dict[str, Any]) -> ScreenContent:
    selected_tariff_raw = state.get("selected_tariff")
    meta = _tariff_meta(selected_tariff_raw)
    if not meta or selected_tariff_raw not in {"T1", "T2", "T3"}:
        return screen_s2(state)

    details = meta.get("details") or "Описание пока недоступно."
    text = _with_screen_prefix(
        "S2_MORE",
        f"{meta['title']}\n\n{details}",
    )
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=_with_button_icons(CTA_LABELS["profile_input"], "➡️"),
                callback_data="s2:details:continue",
            ),
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Назад", "↩️"),
                callback_data="s2:details:back",
            ),
        ]
    ]
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s2_legal(_: dict[str, Any]) -> ScreenContent:
    offer_text = (
        "Оферта и условия использования:\n\n"
        "• Бот формирует аналитический отчёт в нейтральной лексике.\n"
        "• Бот не даёт медицинских, финансовых или правовых рекомендаций.\n"
        "• Запрещены обещания результата и гарантии.\n"
        "• Оплата подтверждает согласие с офертой и условиями сервиса.\n"
        "• Ответственность за решения остаётся за пользователем.\n\n"
        f"{_common_disclaimer_full()}"
    )
    text = _with_screen_prefix("S2", offer_text)
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Назад", "↩️"),
                callback_data="screen:S1",
            )
        ]
    ]
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s3(state: dict[str, Any]) -> ScreenContent:
    selected_tariff_raw = state.get("selected_tariff", "T1")
    selected_tariff = _format_tariff_label(selected_tariff_raw)
    order_status = state.get("order_status")
    price_label = _format_price(state, str(selected_tariff_raw)) or "не указана"
    payment_context = get_payment_flow_context()
    manual_mode = payment_context["mode"] == "manual"
    raw_payment_url = state.get("payment_url")
    payment_url = None
    if not manual_mode and isinstance(raw_payment_url, str):
        candidate_url = raw_payment_url.strip()
        if candidate_url.startswith(("https://", "http://")):
            payment_url = candidate_url

    payment_processing_notice = bool(state.get("payment_processing_notice"))
    order_is_paid = str(order_status or "").lower() == "paid"
    payment_cta = CTA_LABELS["payment"][
        "with_payment_url" if payment_url else "before_payment_url"
    ]

    text_parts = []
    if payment_processing_notice:
        payment_wait_frame = str(state.get("payment_wait_frame") or "⏳")
        text_parts.append(build_payment_wait_message(frame=payment_wait_frame))
    else:
        quick_value_block = [
            "Сразу после оплаты вы получите доступ к персональному отчёту.",
            "Формат результата: PDF с выводами, структурой по сферам и практическими шагами.",
        ]
        bullets = [
            f"Тариф: {selected_tariff}.",
            f"Стоимость: {price_label}.",
        ]
        text_parts.append(
            "\n".join(
                [
                    _build_screen_header("Шаг 3. Подтверждение оплаты"),
                    _build_bullets(bullets),
                    "",
                    _build_bullets(quick_value_block),
                    "",
                    "Без подписки и автосписаний.",
                    (
                        _build_cta_line("Оплатите по реквизитам ниже и отправьте скриншот чека в поддержку.")
                        if manual_mode
                        else _build_cta_line(f"Нажмите «{payment_cta}», чтобы перейти к оплате.")
                    ),
                ]
            )
        )
        if manual_mode:
            manual_card_number = str(payment_context.get("manual_card_number") or "").strip()
            manual_recipient_name = str(payment_context.get("manual_recipient_name") or "").strip()
            if payment_context.get("manual_card_ready"):
                manual_lines = [
                    "Оплата сейчас принимается по ручным реквизитам.",
                    f"Номер карты: {manual_card_number}",
                    "После оплаты отправьте скриншот чека в этот чат (кнопка поддержки).",
                    "Отчёт будет готов в течение 15 минут после подтверждения оплаты.",
                ]
                if manual_recipient_name:
                    manual_lines.append(f"Получатель: {manual_recipient_name}")
                text_parts.append("\n\n" + _build_bullets(manual_lines, EMOJI_ACTION))
            else:
                text_parts.append(
                    "\n\n"
                    + _build_cta_line(
                        "Реквизиты временно недоступны, напишите в поддержку.",
                        EMOJI_WARNING,
                    )
                )
        elif not payment_url:
            support_url = str(getattr(settings, "feedback_group_url", "") or "").strip()
            order_id = str(state.get("order_id") or "").strip() or "не назначен"
            text_parts.append(
                "\n\n"
                + "\n".join(
                    [
                        _build_cta_line(
                            "Платёжная ссылка пока недоступна (provider-режим).",
                            EMOJI_WARNING,
                        ),
                        _build_cta_line(
                            f"Диагностика: order_id={order_id}, payment_url отсутствует.",
                            EMOJI_WARNING,
                        ),
                        _build_cta_line(
                            "Нажмите «Перейти к оплате» для повторной генерации ссылки.",
                        ),
                        _build_cta_line(
                            (
                                "Если ссылка снова не появится — напишите в поддержку."
                                if support_url
                                else "Если ссылка снова не появится — нажмите кнопку поддержки."
                            ),
                        ),
                    ]
                )
            )

    text = "".join(text_parts)
    if not payment_processing_notice:
        text = _with_screen_prefix("S3", text)
    back_target = state.get("s3_back_target") or "S4"
    rows: list[list[InlineKeyboardButton]] = []
    if not payment_processing_notice:
        if order_is_paid:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=_with_button_icons("Продолжить", "✅"),
                        callback_data="payment:paid",
                    )
                ]
            )
        elif payment_url:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=_with_button_icons(payment_cta, "💳"),
                        url=payment_url,
                    ),
                ]
            )
        elif manual_mode and payment_context.get("manual_card_ready"):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=_with_button_icons("Я оплатил(а), отправить скрин", "📎"),
                        callback_data="screen:S8:manual_payment_receipt",
                    ),
                ]
            )
        elif manual_mode and not payment_context.get("manual_card_ready"):
            support_url = str(getattr(settings, "feedback_group_url", "") or "").strip()
            if support_url:
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=_with_button_icons("Написать в поддержку", "💬"),
                            url=support_url,
                        )
                    ]
                )
            else:
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=_with_button_icons("Написать в поддержку", "💬"),
                            callback_data="screen:S8",
                        )
                    ]
                )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=_with_button_icons(payment_cta, "💳"),
                        callback_data="payment:start",
                    ),
                ]
            )
            support_url = str(getattr(settings, "feedback_group_url", "") or "").strip()
            rows.append(
                [
                    InlineKeyboardButton(
                        text=_with_button_icons("Написать в поддержку", "💬"),
                        url=support_url,
                    )
                ]
                if support_url
                else [
                    InlineKeyboardButton(
                        text=_with_button_icons("Написать в поддержку", "💬"),
                        callback_data="screen:S8",
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Назад", "⬅️"),
                    callback_data=f"screen:{back_target}",
                ),
            ]
        )
        rows.extend(_global_menu())
    keyboard = _build_keyboard(rows) if rows else None
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s3_report_details(state: dict[str, Any]) -> ScreenContent:
    selected_tariff = _format_tariff_label(state.get("selected_tariff", "T1"))
    payment_context = get_payment_flow_context()
    manual_mode = payment_context["mode"] == "manual"
    order_id = state.get("order_id")
    order_status = state.get("order_status")
    order_line = ""
    if order_id:
        order_line = f"\nЗаказ №{order_id}"
        if order_status:
            order_line += f" • статус: {order_status}"

    offer_url = settings.offer_url
    offer_line = f"Оплата подтверждает согласие с офертой: {offer_url}." if offer_url else "Оплата подтверждает согласие с офертой."
    manual_sla_line = "\n• Отчёт будет готов в течение 15 минут после подтверждения оплаты." if manual_mode else ""

    text = _with_screen_prefix(
        "S3_INFO",
        (
            f"Что входит в отчёт ({selected_tariff}):\n"
            "• Сразу после оплаты: доступ к персональному отчёту без ожидания.\n"
            "• Формат: PDF с блоками «ключевые выводы», «структура по сферам», «рекомендации».\n"
            "• Применимость: короткий action-план, чтобы перейти к действиям в ближайший период.\n"
            "• Прозрачность: сервис не гарантирует конкретный результат, но даёт практичные ориентиры.\n\n"
            "Юридическая информация:\n"
            f"• {offer_line}\n"
            f"{manual_sla_line}"
            "• Сервис носит информационно-аналитический характер."
            f"{order_line}"
        ),
    )
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("К оплате", "💳"),
                callback_data="s3:report_details:back",
            ),
        ]
    ]
    rows.extend(_global_menu())
    return ScreenContent(messages=[text], keyboard=_build_keyboard(rows))


def _format_birth_place(place: dict[str, Any] | None) -> str:
    if not place:
        return "не указано"
    parts = [place.get("city"), place.get("region"), place.get("country")]
    return ", ".join(part for part in parts if part)


def _format_report_list(reports: list[dict[str, Any]] | None, total: int | None) -> str:
    if not reports:
        return "Отчётов пока нет. После генерации они будут доступны здесь."
    lines = []
    for index, report in enumerate(reports, start=1):
        report_id = report.get("id", "—")
        tariff = tariff_button_title(report.get("tariff"), fallback="—")
        created_at = report.get("created_at", "неизвестно")
        lines.append(f"{index}. Отчёт #{report_id} • {tariff} • {created_at}")
    if total and total > len(reports):
        lines.append(f"\nПоказаны последние {len(reports)} из {total}.")
    return "\n".join(lines)


def _format_questionnaire_profile(
    questionnaire: dict[str, Any] | None,
    *,
    expanded_answers: bool = False,
) -> str:
    if not questionnaire:
        return "Профиль расширенной анкеты: нет данных."
    status = questionnaire.get("status", "empty")
    status_labels = {
        "empty": "не заполнена",
        "in_progress": "в процессе",
        "completed": "завершена",
    }
    display_status = status_labels.get(str(status).lower(), status)
    version = questionnaire.get("version", "—")
    answered_count = questionnaire.get("answered_count", 0)
    total_questions = questionnaire.get("total_questions", 0)
    completed_at = _format_completed_at(questionnaire.get("completed_at"))
    answers = questionnaire.get("answers")
    lines = [
        "🧾 Профиль расширенной анкеты",
        f"• Статус: {display_status}",
        f"• Версия: {version}",
        f"• Прогресс: {answered_count}/{total_questions}",
        f"• Завершена: {completed_at}",
    ]
    if isinstance(answers, dict) and answers:
        questionnaire_config = load_questionnaire_config()
        lines.append("\n💬 Ответы")
        for answer_index, (key, value) in enumerate(answers.items(), start=1):
            question = questionnaire_config.get_question(key)
            label = question.text if question and question.text else (question.question_id if question else key)
            rendered_answer = _format_answer_for_profile(value, expanded=expanded_answers)
            lines.append(f"{answer_index}. {label}\n   {rendered_answer}")
    elif answers:
        rendered_answer = _format_answer_for_profile(answers, expanded=expanded_answers)
        lines.append(f"\n💬 Ответы\n{rendered_answer}")
    else:
        lines.append("\n💬 Ответы\nнет данных.")
    return "\n".join(lines)


def _format_completed_at(raw_completed_at: Any) -> str:
    if not raw_completed_at:
        return "не завершена"
    completed_text = str(raw_completed_at)
    try:
        parsed = datetime.fromisoformat(completed_text)
    except ValueError:
        return completed_text
    return parsed.strftime("%d.%m.%Y %H:%M")


def _format_answer_for_profile(value: Any, *, expanded: bool = False) -> str:
    answer_text = str(value)
    if answer_text == "":
        return "(пусто)"
    clean_answer = _BOT_MENTION_PREFIX_RE.sub("", answer_text)
    if expanded or len(clean_answer) <= _QUESTIONNAIRE_PREVIEW_LIMIT:
        return clean_answer
    return f"{clean_answer[:_QUESTIONNAIRE_PREVIEW_LIMIT].rstrip()}…"


def _format_reports_for_payment_step(
    reports: list[dict[str, Any]] | None,
    total: int | None,
    selected_tariff: str | None,
) -> str:
    if not reports:
        return "Отчётов пока нет. Вы можете продолжить и создать новый заказ."

    filtered_reports = reports
    if selected_tariff:
        filtered_reports = [
            report
            for report in reports
            if str(report.get("tariff", "")).strip() == selected_tariff
        ]

    if not filtered_reports:
        return (
            f"По тарифу {tariff_button_title(selected_tariff, fallback=selected_tariff or '—')} ещё нет сохранённых отчётов. "
            "Вы можете продолжить и создать новый заказ."
        )

    lines = []
    for index, report in enumerate(filtered_reports, start=1):
        report_id = report.get("id", "—")
        tariff = tariff_button_title(report.get("tariff"), fallback="—")
        created_at = report.get("created_at", "неизвестно")
        lines.append(f"{index}. Отчёт #{report_id} • {tariff} • {created_at}")

    if total and selected_tariff is None and total > len(filtered_reports):
        lines.append(f"\nПоказаны последние {len(filtered_reports)} из {total}.")
    return "\n".join(lines)



def _questionnaire_has_long_answers(questionnaire: dict[str, Any] | None) -> bool:
    if not questionnaire:
        return False
    answers = questionnaire.get("answers")
    if isinstance(answers, dict):
        for value in answers.values():
            if len(_format_answer_for_profile(value, expanded=True)) > _QUESTIONNAIRE_PREVIEW_LIMIT:
                return True
        return False
    if answers is None:
        return False
    return len(_format_answer_for_profile(answers, expanded=True)) > _QUESTIONNAIRE_PREVIEW_LIMIT


def screen_s4(state: dict[str, Any]) -> ScreenContent:
    selected_tariff_raw = state.get("selected_tariff", "T0")
    selected_tariff_title = _format_tariff_label(selected_tariff_raw)
    profile = state.get("profile")
    profile_data = profile or {}
    has_profile = profile is not None
    birth_place = _format_birth_place(profile_data.get("birth_place"))
    birth_time = profile_data.get("birth_time") or "не указано"
    profile_flow = state.get("profile_flow")
    opened_from_lk = bool(state.get("s4_opened_from_lk"))
    order_status = (state.get("order_status") or "").lower()
    requires_payment = selected_tariff_raw in {"T1", "T2", "T3"} and order_status != "paid"
    questionnaire = state.get("questionnaire") or {}
    questionnaire_status = str(questionnaire.get("status") or "empty").strip().lower()
    questionnaire_answers = questionnaire.get("answers")
    questionnaire_has_answers = bool(questionnaire_answers) if questionnaire_answers is not None else False
    is_t0 = selected_tariff_raw == "T0"

    is_order_creation_mode = selected_tariff_raw in {"T1", "T2", "T3"}
    show_payment_success_banner = order_status == "paid" and bool(profile_flow)
    payment_success_banner = (
        f"<b>{EMOJI_WARNING} ОПЛАТА ПРОШЛА УСПЕШНО.</b>\n\n" if show_payment_success_banner else ""
    )

    if has_profile:
        bullets = [
            "Данные используются для персонального расчёта отчёта.",
            "При необходимости их можно быстро обновить.",
            (
                f"Имя: {profile_data.get('name')}; Пол: {profile_data.get('gender') or 'не указано'}; "
                f"дата рождения: {profile_data.get('birth_date')}; время: {birth_time}; место: {birth_place}."
            ),
        ]
        text = _with_screen_prefix(
            "S4",
            (
                f"{payment_success_banner}"
                f"{_build_screen_header('Шаг 4. Проверьте данные профиля')}\n"
                f"{_build_bullets(bullets)}\n"
                f"{_build_cta_line('Нажмите «Редактировать» или «Продолжить» для следующего шага.')}"
            ),
        )
    elif is_t0:
        bullets = [
            "Получите краткий срез сильных сторон и зон роста.",
            "Оцените формат полного отчёта до покупки.",
            "Бесплатный доступ к превью доступен один раз в месяц.",
        ]
        text = _with_screen_prefix(
            "S4",
            (
                f"{_build_screen_header('Шаг 4. Данные для бесплатного превью')}\n"
                f"{_build_bullets(bullets)}\n"
                f"{_build_cta_line('Нажмите «Дальше», чтобы начать ввод данных.')}"
            ),
        )
    else:
        bullets = [
            "Данные ещё не заполнены.",
            "Бот запросит имя, пол, дату, время и место рождения.",
            "Эти данные нужны для точного персонального анализа.",
        ]
        text = _with_screen_prefix(
            "S4",
            (
                f"{payment_success_banner}"
                f"{_build_screen_header('Шаг 4. Заполните профиль')}\n"
                f"{_build_bullets(bullets)}\n"
                f"{_build_cta_line('Нажмите «Заполнить данные», чтобы продолжить.')}"
            ),
        )

    if state.get("s4_no_inline_keyboard"):
        return ScreenContent(messages=[text], keyboard=None)

    rows: list[list[InlineKeyboardButton]] = []
    primary_row: list[InlineKeyboardButton] | None = None
    secondary_rows: list[list[InlineKeyboardButton]] = []
    has_tariffs_button = False
    if has_profile:
        secondary_rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Редактировать", "📝"),
                    callback_data="screen:S4_EDIT",
                )
            ]
        )
        if not is_order_creation_mode or opened_from_lk:
            secondary_rows.append(
                [
                    InlineKeyboardButton(
                        text=_with_button_icons("Удалить мои данные", "🗑️"),
                        callback_data="screen:S4_DELETE",
                    )
                ]
            )
    elif is_t0:
        primary_row = [
            InlineKeyboardButton(
                text=_with_button_icons("Дальше", "➡️"),
                callback_data="profile:start",
            )
        ]
        secondary_rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Обратная связь", "💬"),
                    callback_data="screen:S8",
                )
            ]
        )
    elif requires_payment:
        requires_completed_questionnaire = selected_tariff_raw in {"T2", "T3"}
        should_redirect_to_questionnaire = (
            requires_completed_questionnaire and questionnaire_status != "completed"
        )
        primary_button_text = CTA_LABELS["payment"]["before_payment_url"]
        primary_button_icon = "💳"
        primary_button_callback = "screen:S3"
        if should_redirect_to_questionnaire:
            primary_button_text = "Продолжить анкету" if questionnaire_has_answers else CTA_LABELS["questionnaire"]
            primary_button_icon = "📝" if not questionnaire_has_answers else "▶️"
            primary_button_callback = "screen:S5"

        primary_row = [
            InlineKeyboardButton(
                text=_with_button_icons(primary_button_text, primary_button_icon),
                callback_data=primary_button_callback,
            )
        ]
        secondary_rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Тарифы", "🧾"),
                    callback_data="screen:S1",
                )
            ]
        )
        has_tariffs_button = True
    else:
        primary_row = [
            InlineKeyboardButton(
                text=_with_button_icons(CTA_LABELS["profile_input"], "📝"),
                callback_data="profile:start",
            )
        ]
    show_paid_tariff_continue = has_profile and selected_tariff_raw in {"T1", "T2", "T3"} and (
        order_status == "paid" or not order_status
    )
    show_t0_continue = has_profile and is_t0
    show_paid_order_continue_without_tariff = (
        has_profile and order_status == "paid" and not requires_payment
    )
    show_profile_flow_compact_keyboard = profile_flow and has_profile and not requires_payment
    show_continue_button = (
        show_profile_flow_compact_keyboard
        or show_paid_tariff_continue
        or show_t0_continue
        or show_paid_order_continue_without_tariff
    )

    if show_continue_button:
        primary_row = [
            InlineKeyboardButton(
                text=_with_button_icons("Продолжить", "✅"),
                callback_data="profile:save",
            )
        ]

    if not show_profile_flow_compact_keyboard and not is_order_creation_mode:
        secondary_rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Кабинет", "👤"),
                    callback_data="screen:S11",
                )
            ]
        )

    if (not is_t0 or has_profile) and not show_profile_flow_compact_keyboard:
        secondary_rows.extend(_global_menu())

    if not show_profile_flow_compact_keyboard and not has_tariffs_button:
        secondary_rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Тарифы", "➡️"),
                    callback_data="screen:S1",
                )
            ]
        )
    if primary_row is not None:
        rows.append(primary_row)
    rows.extend(secondary_rows)
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s4_edit(state: dict[str, Any]) -> ScreenContent:
    profile = state.get("profile") or {}
    birth_place = _format_birth_place(profile.get("birth_place"))
    birth_time = profile.get("birth_time") or "не указано"
    if not profile:
        text = _with_screen_prefix(
            "S4",
            "Данные ещё не заполнены. Вернитесь назад и заполните профиль.",
        )
        rows = [
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Назад", "↩️"),
                    callback_data="screen:S4",
                )
            ]
        ]
        keyboard = _build_keyboard(rows)
        return ScreenContent(messages=[text], keyboard=keyboard)
    text = _with_screen_prefix(
        "S4",
        (
            "Выберите поле для частичного редактирования:\n\n"
            f"Имя: {profile.get('name')}\n"
            f"Пол: {profile.get('gender') or 'не указано'}\n"
            f"Дата рождения: {profile.get('birth_date')}\n"
            f"Время рождения: {birth_time}\n"
            f"Место рождения: {birth_place}"
        ),
    )
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Имя", "📝"),
                callback_data="profile:edit:name",
            )
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Пол", "⚧️"),
                callback_data="profile:edit:gender",
            )
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Дата рождения", "🗓️"),
                callback_data="profile:edit:birth_date",
            )
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Время рождения", "⏰"),
                callback_data="profile:edit:birth_time",
            )
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Место рождения", "📍"),
                callback_data="profile:edit:birth_place",
            )
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Назад", "↩️"),
                callback_data="screen:S4",
            )
        ],
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s4_consent(_: dict[str, Any]) -> ScreenContent:
    consent_url = settings.legal_consent_url or "https://aireadu.ru/legal/consent/"
    newsletter_consent_url = "https://aireadu.ru/legal/newsletter-consent/"
    text = _with_screen_prefix(
        "S4",
        (
            "Продолжая вы соглашаетесь с [условиями]"
            f"({consent_url}) и подтверждаете [согласие на получение уведомлений]"
            f"({newsletter_consent_url})."
        ),
    )
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Подтвердить", "✅"),
                callback_data="profile:consent:accept",
            )
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Отказ от уведомлений", "📩"),
                callback_data="profile:consent:accept_without_marketing",
            )
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Вернуться к редактированию", "↩️"),
                callback_data="screen:S4_EDIT",
            )
        ],
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s4_delete_confirm(_: dict[str, Any]) -> ScreenContent:
    text = _with_screen_prefix(
        "S4",
        (
            "Вы уверены, что хотите удалить анкетные данные?\n"
            "Профиль, анкеты и история платежей будут удалены, "
            "а отчёты и учётная запись сохранятся."
        ),
    )
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Да", "✅"),
                callback_data="profile:delete:confirm",
            ),
            InlineKeyboardButton(
                text=_with_button_icons("Отмена", "❌"),
                callback_data="screen:S4",
            ),
        ]
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s5(state: dict[str, Any]) -> ScreenContent:
    selected_tariff = _format_tariff_label(state.get("selected_tariff", "T2/T3"))
    questionnaire = state.get("questionnaire") or {}
    answered_count = questionnaire.get("answered_count", 0)
    total_questions = questionnaire.get("total_questions", 0)
    status = questionnaire.get("status", "empty")
    has_paid_order = bool(state.get("order_id")) and str(
        state.get("order_status") or ""
    ).lower() == "paid"
    effective_total_questions = total_questions if total_questions > 0 else 5
    progress_line = f"Прогресс: {answered_count}/{effective_total_questions}."
    eta_line = f"Обычно это {effective_total_questions} вопросов, ~3–5 минут."

    text = _with_screen_prefix(
        "S5",
        "\n".join(
            [
                _build_screen_header("Шаг 5. Дополнительная анкета"),
                _build_bullets(
                    [
                        "Можно начать с коротких ответов.",
                        "Вернуться и дополнить позже.",
                        progress_line,
                        eta_line,
                    ]
                ),
                _build_cta_line("Нажмите кнопку ниже, чтобы заполнить или продолжить анкету."),
            ]
        ),
    ).strip()

    rows: list[list[InlineKeyboardButton]] = []
    primary_row: list[InlineKeyboardButton] | None = None
    secondary_rows: list[list[InlineKeyboardButton]] = []
    if status == "completed":
        primary_row = [
            InlineKeyboardButton(
                text=_with_button_icons("Готово", "✅"),
                callback_data="questionnaire:done",
            )
        ]
        secondary_rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Редактировать анкету", "📝"),
                    callback_data="questionnaire:edit",
                )
            ]
        )
    else:
        if has_paid_order:
            button_text = "Продолжить"
            button_icon = "✅"
        else:
            button_text = "Продолжить анкету" if answered_count else CTA_LABELS["questionnaire"]
            button_icon = "▶️" if answered_count else "📝"
        primary_row = [
            InlineKeyboardButton(
                text=_with_button_icons(button_text, button_icon),
                callback_data="questionnaire:start",
            )
        ]
        if has_paid_order:
            secondary_rows.append(
                [
                    InlineKeyboardButton(
                        text=_with_button_icons("Редактировать анкету", "📝"),
                        callback_data="questionnaire:edit",
                    )
                ]
            )
    secondary_rows.append(
        [
            InlineKeyboardButton(
                text=_with_button_icons("Назад", "↩️"),
                callback_data="screen:S1",
            )
        ]
    )
    secondary_rows.extend(_global_menu())
    if primary_row is not None:
        rows.append(primary_row)
    rows.extend(secondary_rows)
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s6(state: dict[str, Any]) -> ScreenContent:
    job_status = state.get("report_job_status")
    if job_status == "failed":
        text = _with_screen_prefix(
            "S6",
            "\n".join(
                [
                    _build_screen_header("Шаг 6. Подготовка отчёта"),
                    _build_bullets(
                        [
                            "Не удалось сформировать отчёт.",
                            "Попробуйте перейти в тарифы и запустить отчёт снова.",
                        ],
                        emoji=EMOJI_WARNING,
                    ),
                    _build_cta_line("Нажмите «Назад в тарифы», чтобы повторить запуск."),
                ]
            ),
        )
    else:
        text = build_report_wait_message()
    rows = []
    rows.append(
        [
            InlineKeyboardButton(
                text=_with_button_icons("Назад в тарифы", "↩️"),
                callback_data="screen:S1",
            )
        ]
    )
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s7(state: dict[str, Any]) -> ScreenContent:
    canonical_text_from_state = (state.get("report_text_canonical") or "").strip()
    report_text = canonical_text_from_state or build_canonical_report_text(
        (state.get("report_text") or "").strip(),
        tariff=str(state.get("selected_tariff") or "unknown"),
    )
    job_status = state.get("report_job_status")
    disclaimer = _common_disclaimer_short()
    if report_text:
        text = _with_screen_prefix("S7", f"{report_text}\n\n{disclaimer}")
    elif job_status == "failed":
        text = _with_screen_prefix(
            "S7",
            "\n".join(
                [
                    _build_screen_header("Шаг 7. Отчёт"),
                    _build_bullets(
                        [
                            "Не удалось сформировать отчёт.",
                            "Вернитесь в тарифы и запустите отчёт снова.",
                        ],
                        emoji=EMOJI_WARNING,
                    ),
                    _build_cta_line("Нажмите «Продолжить», чтобы вернуться к тарифам."),
                ]
            ),
        )
    elif job_status in {"pending", "in_progress"}:
        text = _with_screen_prefix(
            "S7",
            "\n".join(
                [
                    _build_screen_header("Шаг 7. Отчёт"),
                    _build_bullets(["Отчёт ещё готовится. Пожалуйста, подождите."], emoji=EMOJI_STEP),
                    _build_cta_line("Нажмите «Продолжить» чуть позже."),
                ]
            ),
        )
    else:
        text = _with_screen_prefix(
            "S7",
            "\n".join(
                [
                    _build_screen_header("Шаг 7. Ваш отчёт готов"),
                    _build_bullets(
                        [
                            "Резюме.",
                            "Сильные стороны.",
                            "Зоны потенциального роста.",
                            "Ориентиры по сферам.",
                            disclaimer,
                        ]
                    ),
                    _build_cta_line("Нажмите «Продолжить», чтобы перейти дальше."),
                ]
            ),
        )
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Продолжить", "✅"),
                callback_data="screen:S1",
            )
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Подробнее об условиях", "📄"),
                callback_data="legal:offer",
            )
        ],
    ]
    if settings.community_channel_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Сообщество", "👥"),
                    url=settings.community_channel_url,
                )
            ]
        )
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s8(state: dict[str, Any]) -> ScreenContent:
    feedback_context = str(state.get("s8_context") or "").strip().lower()
    if feedback_context == "manual_payment_receipt":
        text_body = (
            "Отправьте скриншот оплаты в этот чат одним сообщением. "
            "При желании добавьте комментарий к платежу в подписи.\n\n"
            "После проверки оплаты администратор подтвердит заказ и сообщит вам о статусе."
        )
    else:
        text_body = (
            "Напишите нам. Наши администраторы внимательны к вашим обращениям и обожают ваши отзывы ❤️"
        )
    text = _with_screen_prefix(
        "S8",
        text_body,
    )
    return ScreenContent(messages=[text], keyboard=None)


def screen_s9(state: dict[str, Any]) -> ScreenContent:
    next_available = state.get("t0_next_available", "неизвестно")
    text = _with_screen_prefix(
        "S9",
        (
            "Бесплатный отчёт доступен раз в месяц.\n\n"
            f"Следующий доступен: {next_available}."
        ),
    )
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Назад", "⬅️"),
                callback_data="screen:S1",
            )
        ]
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s10(_: dict[str, Any]) -> ScreenContent:
    text = _with_screen_prefix("S10", "Сервис временно недоступен. Попробуйте позже.")
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Тарифы", "🧾"),
                callback_data="screen:S1",
            )
        ],
        *(_global_menu()),
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s11(state: dict[str, Any]) -> ScreenContent:
    profile = state.get("profile") or {}
    birth_place = _format_birth_place(profile.get("birth_place"))
    birth_time = profile.get("birth_time") or "не указано"
    reports_total = state.get("reports_total")
    reports_line = ""
    if reports_total is not None:
        reports_line = f"\n\n📁 Сохранённых отчётов: {reports_total}."
    questionnaire_expanded = bool(state.get("questionnaire_answers_expanded"))
    questionnaire_text = _format_questionnaire_profile(
        state.get("questionnaire"),
        expanded_answers=questionnaire_expanded,
    )
    questionnaire = state.get("questionnaire") or {}
    questionnaire_status = questionnaire.get("status", "empty")

    if profile:
        text = _with_screen_prefix(
            "S11",
            (
                "👤 Личный кабинет\n\n"
                "🧩 Основные данные\n"
                f"• Имя: {profile.get('name')}\n"
                f"• Пол: {profile.get('gender') or 'не указано'}\n"
                f"• Дата рождения: {profile.get('birth_date')}\n"
                f"• Время рождения: {birth_time}\n"
                f"• Место рождения: {birth_place}"
                f"{reports_line}\n\n{questionnaire_text}"
            ),
        )
    else:
        text = _with_screen_prefix(
            "S11",
            "👤 Личный кабинет\n\nДанные профиля ещё не заполнены."
            f"{reports_line}\n\n{questionnaire_text}",
        )

    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Мои отчёты", "🗂️"),
                callback_data="screen:S12",
            )
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Мои данные", "🧩"),
                callback_data="screen:S4",
            )
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Редактировать анкету", "📝"),
                callback_data="questionnaire:edit:lk",
            )
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Обратная связь", "💬"),
                callback_data="screen:S8",
            )
        ],
    ]
    if questionnaire_status != "empty":
        rows.insert(
            3,
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Удалить анкету", "🗑️"),
                    callback_data="questionnaire:delete:lk",
                )
            ],
        )
    if _questionnaire_has_long_answers(questionnaire):
        rows.insert(
            3,
            [
                InlineKeyboardButton(
                    text=_with_button_icons(
                        "Свернуть ответы" if questionnaire_expanded else "Показать ответы полностью",
                        "↕️",
                    ),
                    callback_data=(
                        "questionnaire:answers:collapse"
                        if questionnaire_expanded
                        else "questionnaire:answers:expand"
                    ),
                )
            ],
        )
    if settings.community_channel_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Сообщество", "👥"),
                    url=settings.community_channel_url,
                )
            ]
        )
    rows.extend(
        [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Тарифы", "🧾"),
                callback_data="screen:S1",
            )
        ],
        *(_global_menu()),
    ]
    )
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s12(state: dict[str, Any]) -> ScreenContent:
    reports = state.get("reports") or []
    reports_total = state.get("reports_total")
    text = _with_screen_prefix(
        "S12",
        "Мои отчёты:\n\n" + _format_report_list(reports, reports_total),
    )
    rows: list[list[InlineKeyboardButton]] = []
    for report in reports:
        report_id = report.get("id")
        if report_id is None:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons(f"Открыть #{report_id}", "📖"),
                    callback_data=f"report:view:{report_id}",
                ),
                InlineKeyboardButton(
                    text=_with_button_icons("Удалить", "🗑️"),
                    callback_data=f"report:delete:{report_id}",
                ),
            ]
        )
    if reports:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Удалить все отчёты", "🗑️"),
                    callback_data="report:delete_all",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=_with_button_icons("Назад", "↩️"),
                callback_data="screen:S11",
            )
        ]
    )
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s13(state: dict[str, Any]) -> ScreenContent:
    report_meta = state.get("report_meta") or {}
    canonical_text_from_state = (state.get("report_text_canonical") or "").strip()
    report_text = canonical_text_from_state or build_canonical_report_text(
        (state.get("report_text") or "").strip(),
        tariff=str(report_meta.get("tariff") or state.get("selected_tariff") or "unknown"),
    )
    report_id_value = str(report_meta.get("id") or "")
    report_id = report_id_value or "—"
    report_tariff = report_meta.get("tariff", "—")
    report_created_at = report_meta.get("created_at", "неизвестно")
    disclaimer = (
        "Сервис не является консультацией, прогнозом или рекомендацией к действию.\n"
        "Все выводы носят аналитический и описательный характер.\n"
        "Ответственность за решения остаётся за пользователем.\n"
        "Сервис не гарантирует финансовых или иных результатов.\n"
    )
    header = (
        f"Отчёт #{report_id}\n"
        f"Тариф: {report_tariff}\n"
        f"Дата: {report_created_at}\n\n"
    )
    if report_text:
        text = _with_screen_prefix("S13", f"{header}{report_text}\n\n{disclaimer}")
    else:
        text = _with_screen_prefix(
            "S13",
            f"{header}Текст отчёта недоступен. Попробуйте выбрать другой отчёт.",
        )

    rows = []
    if report_id_value:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Выгрузить PDF", "📄"),
                    callback_data=f"report:pdf:{report_id_value}",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Удалить отчёт", "🗑️"),
                    callback_data=f"report:delete:{report_id_value}",
                )
            ]
        )
    if settings.community_channel_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Сообщество", "👥"),
                    url=settings.community_channel_url,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=_with_button_icons("Назад к списку", "↩️"),
                callback_data="screen:S12",
            )
        ]
    )
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)




def screen_s15(state: dict[str, Any]) -> ScreenContent:
    selected_tariff = state.get("selected_tariff")
    reports = state.get("reports") or []
    reports_total = state.get("reports_total")
    reports_list = _format_reports_for_payment_step(
        reports,
        reports_total,
        selected_tariff,
    )
    text = _with_screen_prefix(
        "S15",
        (
            f"Перед оплатой тарифа {tariff_button_title(selected_tariff, fallback='T1/T2/T3')} посмотрите последние отчёты:\n\n"
            f"{reports_list}\n\n"
            "Можно перейти в личный кабинет или к оплате и создать новый заказ."
        ),
    )
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("К оплате", "💳"),
                callback_data="existing_report:continue",
            )
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Перейти в ЛК", "🗂️"),
                callback_data="existing_report:lk",
            )
        ],
    ]
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s14(state: dict[str, Any]) -> ScreenContent:
    delete_scope = state.get("report_delete_scope")
    report_meta = state.get("report_meta") or {}
    report_id = report_meta.get("id", "—")
    if delete_scope == "all":
        text = _with_screen_prefix(
            "S14",
            "Удалить все отчёты? Это действие нельзя отменить.",
        )
        confirm_callback = "report:delete:confirm_all"
        cancel_callback = "screen:S12"
    else:
        text = _with_screen_prefix(
            "S14",
            f"Удалить отчёт #{report_id}? Это действие нельзя отменить.",
        )
        confirm_callback = "report:delete:confirm"
        cancel_callback = "screen:S13"
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Удалить", "✅"),
                callback_data=confirm_callback,
            ),
            InlineKeyboardButton(
                text=_with_button_icons("Отмена", "❌"),
                callback_data=cancel_callback,
            ),
        ],
    ]
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_marketing_consent(_: dict[str, Any]) -> ScreenContent:
    text = _with_screen_prefix(
        "S_MARKETING_CONSENT",
        "Хочешь получать короткие полезные разборы, анонсы обновлений и спец-предложения?\n"
        "Мы пишем по делу и без спама.\n\n"
        "Условия подписки: https://aireadu.ru/legal/newsletter-consent/",
    )
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Подписаться", "✅"),
                callback_data="marketing:consent:accept",
            )
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Не сейчас", "⏭️"),
                callback_data="marketing:consent:skip",
            )
        ],
    ]
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


SCREEN_REGISTRY = {
    "S0": screen_s0,
    "S1": screen_s1,
    "S2": screen_s2,
    "S2_LEGAL": screen_s2_legal,
    "S2_MORE": screen_s2_details,
    "S3": screen_s3,
    "S3_INFO": screen_s3_report_details,
    "S4": screen_s4,
    "S4_EDIT": screen_s4_edit,
    "S4_CONSENT": screen_s4_consent,
    "S4_DELETE": screen_s4_delete_confirm,
    "S5": screen_s5,
    "S6": screen_s6,
    "S7": screen_s7,
    "S8": screen_s8,
    "S9": screen_s9,
    "S10": screen_s10,
    "S11": screen_s11,
    "S12": screen_s12,
    "S13": screen_s13,
    "S14": screen_s14,
    "S15": screen_s15,
    "S_MARKETING_CONSENT": screen_marketing_consent,
}
