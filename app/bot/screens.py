from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.config import settings


@dataclass(frozen=True)
class ScreenContent:
    messages: list[str]
    keyboard: InlineKeyboardMarkup | None = None


def _global_menu() -> list[list[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton(text="Тарифы", callback_data="screen:S1"),
            InlineKeyboardButton(text="Мои данные", callback_data="screen:S4"),
        ],
        [
            InlineKeyboardButton(text="Оферта", callback_data="screen:S2"),
            InlineKeyboardButton(text="Обратная связь", callback_data="screen:S8"),
        ],
    ]


def _build_keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in rows:
        builder.row(*row)
    return builder.as_markup()


def _format_tariff_label(tariff: str) -> str:
    if tariff == "T0":
        return "Т0"
    return tariff


def screen_s0(_: dict[str, Any]) -> ScreenContent:
    text = (
        "ИИ-аналитик личных данных помогает структурировать опыт и увидеть рабочие гипотезы.\n\n"
        "Сервис не является консультацией, прогнозом или рекомендацией к действию. 🙂"
    )
    keyboard = _build_keyboard(_global_menu())
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s1(_: dict[str, Any]) -> ScreenContent:
    text = (
        "Тарифы:\n\n"
        "Т0 — 0 ₽ (1 раз в месяц)\n"
        "T1 — 560 ₽\n"
        "T2 — 2190 ₽\n"
        "T3 — 5930 ₽\n\n"
        "Выберите тариф, чтобы продолжить."
    )
    rows = [
        [
            InlineKeyboardButton(text="Получить Т0", callback_data="tariff:T0"),
        ],
        [
            InlineKeyboardButton(text="Выбрать T1", callback_data="tariff:T1"),
            InlineKeyboardButton(text="Выбрать T2", callback_data="tariff:T2"),
            InlineKeyboardButton(text="Выбрать T3", callback_data="tariff:T3"),
        ],
        *_global_menu(),
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s2(state: dict[str, Any]) -> ScreenContent:
    selected_tariff = _format_tariff_label(state.get("selected_tariff", "T1–T3"))
    text = (
        f"Оферта и правила перед оплатой ({selected_tariff}).\n\n"
        "Сервис не является консультацией, прогнозом или рекомендацией к действию.\n"
        "Все выводы носят аналитический и описательный характер.\n"
        "Ответственность за решения остаётся за пользователем.\n"
        "Сервис не гарантирует финансовых или иных результатов.\n\n"
        "Возвратов нет."
    )
    rows = [
        [
            InlineKeyboardButton(text="Открыть оферту", url=settings.offer_url),
        ],
        [
            InlineKeyboardButton(text="Назад к тарифам", callback_data="screen:S1"),
            InlineKeyboardButton(text="К оплате", callback_data="screen:S3"),
        ],
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s3(state: dict[str, Any]) -> ScreenContent:
    selected_tariff = _format_tariff_label(state.get("selected_tariff", "T1–T3"))
    order_id = state.get("order_id")
    order_status = state.get("order_status")
    order_amount = state.get("order_amount")
    order_currency = state.get("order_currency", "RUB")
    payment_url = state.get("payment_url") or settings.prodamus_form_url
    order_block = ""
    if order_id and order_status:
        order_block = (
            f"\n\nЗаказ №{order_id}. "
            f"Статус: {order_status}. "
            f"Сумма: {order_amount} {order_currency}."
        )
    text = (
        f"Оплата тарифа {selected_tariff}.\n\n"
        "Оплачивая, вы подтверждаете согласие с офертой. Возвратов нет."
        f"{order_block}"
    )
    rows: list[list[InlineKeyboardButton]] = []
    if payment_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Перейти к оплате",
                    url=payment_url,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="Я оплатил(а)", callback_data="payment:paid"),
            InlineKeyboardButton(text="Назад к тарифам", callback_data="screen:S1"),
        ]
    )
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def _format_birth_place(place: dict[str, Any] | None) -> str:
    if not place:
        return "не указано"
    parts = [place.get("city"), place.get("region"), place.get("country")]
    return ", ".join(part for part in parts if part)


def screen_s4(state: dict[str, Any]) -> ScreenContent:
    selected_tariff = _format_tariff_label(state.get("selected_tariff", "T0"))
    profile = state.get("profile") or {}
    birth_place = _format_birth_place(profile.get("birth_place"))
    birth_time = profile.get("birth_time") or "не указано"
    profile_flow = state.get("profile_flow")
    if profile:
        text = (
            f"Мои данные для тарифа {selected_tariff}:\n\n"
            f"Имя: {profile.get('name')}\n"
            f"Дата рождения: {profile.get('birth_date')}\n"
            f"Время рождения: {birth_time}\n"
            f"Место рождения: {birth_place}\n\n"
            "Это режим просмотра. Для изменения данных нажмите «Перезаполнить»."
        )
    else:
        text = (
            f"Мои данные для тарифа {selected_tariff}.\n\n"
            "Данные ещё не заполнены. Нажмите «Заполнить данные» и следуйте шагам:\n"
            "1) Имя\n"
            "2) Дата рождения (YYYY-MM-DD)\n"
            "3) Время рождения (HH)\n"
            "4) Место рождения (город, регион, страна)."
        )
    rows: list[list[InlineKeyboardButton]] = []
    if profile:
        rows.append(
            [InlineKeyboardButton(text="Перезаполнить", callback_data="profile:start")]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="Заполнить данные", callback_data="profile:start")]
        )
    if profile_flow and profile:
        rows.append(
            [InlineKeyboardButton(text="Продолжить", callback_data="profile:save")]
        )
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s5(state: dict[str, Any]) -> ScreenContent:
    selected_tariff = _format_tariff_label(state.get("selected_tariff", "T2/T3"))
    text = (
        f"Лайтовая анкета для {selected_tariff}.\n\n"
        "1) Опыт и проекты\n"
        "2) Навыки (шкала 1–5)\n"
        "3) Интересы и мотивация\n"
        "4) Ограничения (время/ресурсы)\n"
        "5) Цели\n\n"
        "Заполните ответы и нажмите «Готово»."
    )
    rows = [
        [
            InlineKeyboardButton(text="Готово", callback_data="questionnaire:done"),
            InlineKeyboardButton(text="Назад к тарифам", callback_data="screen:S1"),
        ],
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s6(_: dict[str, Any]) -> ScreenContent:
    text = "Генерируем отчёт… Пожалуйста, подождите."
    rows = [[InlineKeyboardButton(text="Назад в тарифы", callback_data="screen:S1")]]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s7(state: dict[str, Any]) -> ScreenContent:
    report_text = state.get("report_text")
    if report_text:
        text = report_text
    else:
        text = (
            "Ваш отчёт готов.\n\n"
            "• Резюме\n"
            "• Сильные стороны\n"
            "• Зоны потенциального роста\n"
            "• Ориентиры по сферам\n\n"
            "Сервис не является консультацией, прогнозом или рекомендацией к действию.\n"
            "Все выводы носят аналитический и описательный характер.\n"
            "Ответственность за решения остаётся за пользователем.\n"
            "Сервис не гарантирует финансовых или иных результатов.\n"
            "Возвратов нет."
        )
    rows = [
        [
            InlineKeyboardButton(text="Выгрузить PDF", callback_data="report:pdf"),
        ],
        [
            InlineKeyboardButton(text="Тарифы", callback_data="screen:S1"),
            InlineKeyboardButton(text="Обратная связь", callback_data="screen:S8"),
        ],
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s8(_: dict[str, Any]) -> ScreenContent:
    text = (
        "Напишите сообщение. Нажмите «Отправить», чтобы опубликовать его в группе, "
        "или «Перейти в группу»."
    )
    rows = [
        [
            InlineKeyboardButton(text="Отправить", callback_data="feedback:send"),
        ]
    ]
    if settings.feedback_group_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Перейти в группу",
                    url=settings.feedback_group_url,
                )
            ]
        )
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s9(state: dict[str, Any]) -> ScreenContent:
    next_available = state.get("t0_next_available", "неизвестно")
    text = (
        "Бесплатный отчёт доступен раз в месяц.\n\n"
        f"Следующий доступен: {next_available}."
    )
    rows = [
        [InlineKeyboardButton(text="Тарифы", callback_data="screen:S1")],
        *(_global_menu()),
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s10(_: dict[str, Any]) -> ScreenContent:
    text = "Сервис временно недоступен. Попробуйте позже."
    rows = [
        [InlineKeyboardButton(text="Тарифы", callback_data="screen:S1")],
        *(_global_menu()),
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


SCREEN_REGISTRY = {
    "S0": screen_s0,
    "S1": screen_s1,
    "S2": screen_s2,
    "S3": screen_s3,
    "S4": screen_s4,
    "S5": screen_s5,
    "S6": screen_s6,
    "S7": screen_s7,
    "S8": screen_s8,
    "S9": screen_s9,
    "S10": screen_s10,
}
