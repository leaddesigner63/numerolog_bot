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


def _offer_url() -> str | None:
    url = (settings.offer_url or "").strip()
    return url or None


def _offer_button() -> InlineKeyboardButton | None:
    url = _offer_url()
    if not url:
        return None
    return InlineKeyboardButton(text="Открыть оферту", url=url)


def _refunds_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="Возвратов нет", callback_data="noop:refunds")


def _with_screen_prefix(screen_id: str, text: str) -> str:
    return f"{screen_id}: {text.lstrip()}"


def screen_s0(_: dict[str, Any]) -> ScreenContent:
    text = _with_screen_prefix(
        "S0",
        "Бот уже готов разобрать твои данные и показать, в чём твоя сила. "
        "В бесплатном превью ты увидишь несколько своих сильных сторон, возможные зоны роста "
        "и структуру полного отчёта. Без мистики и обещаний — только факты и гипотезы. "
        "Хочешь больше конкретики? Жми «Далее»  и получи подробный анализ, сценарии и план. "
        "Отчёт можно сохранить в PDF. Хочешь начать с малого или сразу перейди к глубине — "
        "решать тебе."
    )
    keyboard = _build_keyboard(
        [[InlineKeyboardButton(text="Далее...", callback_data="screen:S1")]],
    )
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s1(_: dict[str, Any]) -> ScreenContent:
    text = _with_screen_prefix(
        "S1",
        "ИИ горит весь от нетерпения начать работу. Мы не гадаем по звёздам, а "
        "анализируем твои данные.  Выбери свой путь с чего начнём!"
    )
    rows = [
        [
            InlineKeyboardButton(
                text="Твое новое начало(Бесплатно)", callback_data="tariff:T0"
            ),
        ],
        [
            InlineKeyboardButton(text="В чем твоя сила?", callback_data="tariff:T1"),
        ],
        [
            InlineKeyboardButton(text="Где твои деньги?", callback_data="tariff:T2"),
        ],
        [
            InlineKeyboardButton(text="Твой путь к себе!", callback_data="tariff:T3"),
        ],
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s2(state: dict[str, Any]) -> ScreenContent:
    selected_tariff = _format_tariff_label(state.get("selected_tariff", "T1–T3"))
    text = _with_screen_prefix(
        "S2",
        (
            f"Оферта и правила перед оплатой ({selected_tariff}).\n\n"
            "Сервис не является консультацией, прогнозом или рекомендацией к действию.\n"
            "Все выводы носят аналитический и описательный характер.\n"
            "Ответственность за решения остаётся за пользователем.\n"
            "Сервис не гарантирует финансовых или иных результатов.\n\n"
            "Возвратов нет."
        ),
    )
    offer_button = _offer_button()
    if not offer_button:
        text += "\n\nСсылка на оферту пока не настроена."
    rows = [[_refunds_button()]]
    if offer_button:
        rows.append([offer_button])
    rows.append(
        [
            InlineKeyboardButton(text="Назад к тарифам", callback_data="screen:S1"),
            InlineKeyboardButton(text="К оплате", callback_data="screen:S3"),
        ],
    )
    rows.extend(_global_menu())
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
    text = _with_screen_prefix(
        "S3",
        (
            f"Оплата тарифа {selected_tariff}.\n\n"
            "Оплачивая, вы подтверждаете согласие с офертой. Возвратов нет."
            f"{order_block}"
        ),
    )
    offer_button = _offer_button()
    if not offer_button:
        text += "\n\nСсылка на оферту пока не настроена."
    rows: list[list[InlineKeyboardButton]] = []
    rows.append([_refunds_button()])
    if offer_button:
        rows.append([offer_button])
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
    rows.extend(_global_menu())
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
    is_t0 = selected_tariff == "Т0"
    if profile:
        text = _with_screen_prefix(
            "S4",
            (
                f"Мои данные для тарифа {selected_tariff}:\n\n"
                f"Имя: {profile.get('name')}\n"
                f"Дата рождения: {profile.get('birth_date')}\n"
                f"Время рождения: {birth_time}\n"
                f"Место рождения: {birth_place}\n\n"
                "Это режим просмотра. Для изменения данных нажмите «Перезаполнить»."
            ),
        )
    elif is_t0:
        text = _with_screen_prefix(
            "S4",
            (
                "В бесплатном превью-отчёте ты увидишь, на что он обратил внимание в первую "
                "очередь: ключевые сильные стороны, возможные зоны роста и формат полного "
                "анализа. Коротко и по делу. Начни с малого — дальше решать тебе. Краткий мини "
                "отчёт (~30 % полного): несколько сильных сторон, возможные зоны роста и "
                "аккуратная ретроспектива, чтобы оценить подход. Кстати, это честный бесплатный "
                "доступ, поэтому можно всего раз в месяц."
            ),
        )
    else:
        text = _with_screen_prefix(
            "S4",
            (
                f"Мои данные для тарифа {selected_tariff}.\n\n"
                "Данные ещё не заполнены. Нажмите «Заполнить данные» и следуйте шагам:\n"
                "1) Имя\n"
                "2) Дата рождения (YYYY-MM-DD)\n"
                "3) Время рождения (HH:MM)\n"
                "4) Место рождения (город, регион, страна)."
            ),
        )
    rows: list[list[InlineKeyboardButton]] = []
    if profile:
        rows.append(
            [InlineKeyboardButton(text="Перезаполнить", callback_data="profile:start")]
        )
    elif is_t0:
        rows.append([InlineKeyboardButton(text="Старт", callback_data="profile:start")])
        rows.append([InlineKeyboardButton(text="Назад", callback_data="screen:S1")])
        rows.append(
            [InlineKeyboardButton(text="Обратная связь", callback_data="screen:S8")]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="Заполнить данные", callback_data="profile:start")]
        )
    if profile_flow and profile:
        rows.append(
            [InlineKeyboardButton(text="Продолжить", callback_data="profile:save")]
        )
    if not is_t0 or profile:
        rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s5(state: dict[str, Any]) -> ScreenContent:
    selected_tariff = _format_tariff_label(state.get("selected_tariff", "T2/T3"))
    questionnaire = state.get("questionnaire") or {}
    answered_count = questionnaire.get("answered_count", 0)
    total_questions = questionnaire.get("total_questions", 0)
    status = questionnaire.get("status", "empty")
    progress_line = ""
    if total_questions:
        progress_line = f"Прогресс: {answered_count}/{total_questions}."

    text = _with_screen_prefix(
        "S5",
        f"Лайтовая анкета для {selected_tariff}.\n\n"
        "1) Опыт и проекты\n"
        "2) Навыки (шкала 1–5)\n"
        "3) Интересы и мотивация\n"
        "4) Ограничения (время/ресурсы)\n"
        "5) Цели\n\n"
        f"{progress_line}"
    ).strip()
    rows: list[list[InlineKeyboardButton]] = []
    if status == "completed":
        rows.append([InlineKeyboardButton(text="Пройти заново", callback_data="questionnaire:restart")])
        rows.append([InlineKeyboardButton(text="Готово", callback_data="questionnaire:done")])
    else:
        button_text = "Продолжить анкету" if answered_count else "Заполнить анкету"
        rows.append(
            [InlineKeyboardButton(text=button_text, callback_data="questionnaire:start")]
        )
    rows.append([InlineKeyboardButton(text="Назад к тарифам", callback_data="screen:S1")])
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s6(_: dict[str, Any]) -> ScreenContent:
    text = _with_screen_prefix("S6", "Генерируем отчёт… Пожалуйста, подождите.")
    rows = [
        [InlineKeyboardButton(text="Назад в тарифы", callback_data="screen:S1")],
        *_global_menu(),
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s7(state: dict[str, Any]) -> ScreenContent:
    report_text = (state.get("report_text") or "").strip()
    disclaimer = (
        "Сервис не является консультацией, прогнозом или рекомендацией к действию.\n"
        "Все выводы носят аналитический и описательный характер.\n"
        "Ответственность за решения остаётся за пользователем.\n"
        "Сервис не гарантирует финансовых или иных результатов.\n"
        "Возвратов нет."
    )
    if report_text:
        text = _with_screen_prefix("S7", f"{report_text}\n\n{disclaimer}")
    else:
        text = _with_screen_prefix(
            "S7",
            (
                "Ваш отчёт готов.\n\n"
                "• Резюме\n"
                "• Сильные стороны\n"
                "• Зоны потенциального роста\n"
                "• Ориентиры по сферам\n\n"
                f"{disclaimer}"
            ),
        )
    rows = [
        [
            InlineKeyboardButton(text="Выгрузить PDF", callback_data="report:pdf"),
        ],
        *_global_menu(),
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s8(_: dict[str, Any]) -> ScreenContent:
    text = _with_screen_prefix(
        "S8",
        (
            "Напишите сообщение. Нажмите «Отправить», чтобы опубликовать его в группе, "
            "или «Перейти в группу»."
        ),
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
    text = _with_screen_prefix(
        "S9",
        (
            "Бесплатный отчёт доступен раз в месяц.\n\n"
            f"Следующий доступен: {next_available}."
        ),
    )
    rows = [
        [InlineKeyboardButton(text="Тарифы", callback_data="screen:S1")],
        *(_global_menu()),
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s10(_: dict[str, Any]) -> ScreenContent:
    text = _with_screen_prefix("S10", "Сервис временно недоступен. Попробуйте позже.")
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
