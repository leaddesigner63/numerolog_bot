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


# Единый справочник тарифов (чтобы UI не расходился с логикой оплаты)
TARIFF_META: dict[str, dict[str, Any]] = {
    "T0": {
        "title": "Т0 - Твоё новое начало (бесплатно)",
        "price": 0,
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
        "title": "Т1 - В чём твоя сила?",
        "price": 560,
        "bullets": [
            "А ты уже знаешь в чём твоя сила? Ты ярче, чем думаешь. ИИ уже видит твой потенциал. "
            "Он раскроет твои предрасположенности, таланты и зоны роста всего за 560р. "
            "Ты получишь чёткое понимание своих сильных сторон и гипотезы, куда двигаться дальше.🧗‍♀️\n"
            "Жми Далее!) Зажги огонь в себе прямо сейчас и раскрой свою силу по настоящему!🔥",
        ],
        "note": None,
    },
    "T2": {
        "title": "Т2 - Где твои деньги?",
        "price": 2190,
        "bullets": [
            "Беспокоишься о деньгах и будущем? Остынь!😏\n"
            "За 2190 р ИИ копает намного глубже: Анализирует тебя с упором на доход и моделирует сценарии "
            "твоего будущего. Ты узнаешь, где спрятаны возможности роста дохода, какие повороты возможны в "
            "твоей жизни и как реализовать свои способности на полную.💵 Здесь ты получишь Отчёт + фокус на деньги!\n"
            "Ну что, приступим к осмыслению своих возможностей?)👨‍💻",
        ],
        "note": None,
    },
    "T3": {
        "title": "Т3 - Твой путь к себе!",
        "price": "||5930||",
        "bullets": [
            "А ты знаешь, что можешь достичь большего, но не представляешь, с чего начать? Хватит действовать вслепую — "
            "тебе нужен чёткий план!🗓\n"
            "ИИ составит его специально под тебя.🏋️‍♀️\n"
            "Результат придаст твоей жизни движение вперед к новым победам: ты получишь персональный маршрут с чёткими "
            "шагами, сроками и рекомендациями — что, когда и как делать, чтобы раскрыть свой потенциал и жить по максимуму.🏆\n"
            "Успей получить «Твой путь к себе» всего за ||5930||, жми \"Старт💥\" и начнем Твой путь к Себе!",
        ],
        "note": None,
    },
}


def _global_menu() -> list[list[InlineKeyboardButton]]:
    if not settings.global_menu_enabled:
        return []
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


def _with_screen_prefix(screen_id: str, text: str) -> str:
    return f"{screen_id}: {text.lstrip()}"


def _common_disclaimer_short() -> str:
    return (
        "Важно:\n"
        "• Сервис не является консультацией, прогнозом или рекомендацией к действию.\n"
        "• Все выводы носят аналитический и описательный характер.\n"
        "• Ответственность за решения остаётся за пользователем.\n"
        "• Сервис не гарантирует финансовых или иных результатов.\n"
        "• Возвратов нет."
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
    meta = TARIFF_META.get(tariff)
    if not meta:
        return ""
    return f"{meta.get('price')} RUB"


def screen_s0(_: dict[str, Any]) -> ScreenContent:
    text = _with_screen_prefix(
        "S0",
        "Бот уже готов разобрать твои данные и показать, в чём твоя сила. 🦾\n"
        "Кстати, в бесплатном превью ты увидишь несколько своих сильных сторон, возможные зоны роста "
        "и структуру полного отчёта. Без мистики и обещаний — только факты и гипотезы. "
        "Хочешь узнать больше?  Жми Далее😎"
    )
    rows = [
        [InlineKeyboardButton(text="Далее", callback_data="screen:S1")],
        
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s1(_: dict[str, Any]) -> ScreenContent:
    text = _with_screen_prefix(
        "S1",
        "ИИ горит весь от нетерпения начать работу. Он не гадает по звёздам, а анализируем твои данные.  Выбери свой путь с чего начнём!🚀"
    )
    rows = [
        [
            InlineKeyboardButton(
                text="Т0 - Твоё новое начало (бесплатно)", callback_data="tariff:T0"
            ),
        ],
        [
            InlineKeyboardButton(text="Т1 - В чём твоя сила?", callback_data="tariff:T1"),
        ],
        [
            InlineKeyboardButton(text="Т2 - Где твои деньги?", callback_data="tariff:T2"),
        ],
        [
            InlineKeyboardButton(text="Т3 - Твой путь к себе!", callback_data="tariff:T3"),
        ],
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s2(state: dict[str, Any]) -> ScreenContent:
    """
    S2 выполняет две роли:
    - Если selected_tariff = T1/T2/T3: экран описания выбранного тарифа + переход к оплате.
    - Если тариф не выбран: экран оферты/правил (доступен из меню).
    """
    selected_tariff_raw = state.get("selected_tariff")
    meta = _tariff_meta(selected_tariff_raw)

    # 1) Если нет тарифа — показываем оферту/правила
    if not meta or selected_tariff_raw not in {"T1", "T2", "T3"}:
        offer_text = (
            "Оферта и правила:\n\n"
            "• Бот формирует аналитический отчёт в нейтральной лексике.\n"
            "• Бот не даёт медицинских/финансовых/правовых рекомендаций.\n"
            "• Запрещены обещания результата и гарантии.\n\n"
            f"{_common_disclaimer_short()}"
        )
        text = _with_screen_prefix("S2", offer_text)

        rows: list[list[InlineKeyboardButton]] = []
        rows.append([InlineKeyboardButton(text="Назад к тарифам", callback_data="screen:S1")])
        rows.extend(_global_menu())
        keyboard = _build_keyboard(rows)
        return ScreenContent(messages=[text], keyboard=keyboard)

    # 2) Тариф выбран (T1/T2/T3) — показываем описание тарифа
    price = _format_price(state, selected_tariff_raw)
    bullets = meta.get("bullets") or []
    bullets_text = "\n".join([f"• {item}" for item in bullets])

    note = meta.get("note")
    note_text = f"\n\nПримечание: {note}" if note else ""
    text = _with_screen_prefix(
        "S2",
        (
            f"{meta['title']}\n"
            f"Стоимость: {price}\n\n"
            "__________________________________\n"
            f"{bullets_text}"
            f"{note_text}"
            "\n\n"
            "__________________________________\n"
            
        ),
    )

    rows: list[list[InlineKeyboardButton]] = []
    rows.append(
        [
            InlineKeyboardButton(text="Назад к тарифам", callback_data="screen:S1"),
            InlineKeyboardButton(text="Старт💥", callback_data="screen:S3"),
        ]
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

    text_parts = [
        f"Оплата тарифа {selected_tariff}.\n\n"
        "Оплачивая, вы подтверждаете согласие с офертой."
        f"{order_block}"
    ]
    if not payment_url:
        text_parts.append("\n\nПлатёжная ссылка пока недоступна. Проверьте настройки провайдера.")

    text = _with_screen_prefix("S3", "".join(text_parts))

    offer_button = _offer_button()
    if not offer_button:
        text += "\n\nСсылка на оферту пока не настроена."

    rows: list[list[InlineKeyboardButton]] = []
    if offer_button:
        rows.append([offer_button])
    if payment_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Далее!🔥🔥🔥",
                    url=payment_url,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="Я оплатил(а)", callback_data="payment:paid"),
            InlineKeyboardButton(text="Назад", callback_data="screen:S1"),
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
    selected_tariff_raw = state.get("selected_tariff", "T0")
    selected_tariff = _format_tariff_label(selected_tariff_raw)
    profile = state.get("profile") or {}
    birth_place = _format_birth_place(profile.get("birth_place"))
    birth_time = profile.get("birth_time") or "не указано"
    profile_flow = state.get("profile_flow")
    order_status = (state.get("order_status") or "").lower()
    requires_payment = selected_tariff_raw in {"T1", "T2", "T3"} and order_status != "paid"
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
                "Для изменения данных нажмите «Перезаполнить»."
            ),
        )
    elif is_t0:
        text = _with_screen_prefix(
            "S4",
            (
                "Т0 - Твоё новое начало (бесплатно). Вы увидите витрину структуры полного отчёта и краткий "
                "аналитический текст: сильные стороны, зоны роста и нейтральная ретроспектива. "
                "Доступ ограничен: 1 раз в месяц."
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
        rows.append(
            [InlineKeyboardButton(text="Обратная связь", callback_data="screen:S8")]
        )
    elif requires_payment:
        rows.append([InlineKeyboardButton(text="К оплате", callback_data="screen:S3")])
        rows.append([InlineKeyboardButton(text="Тарифы", callback_data="screen:S1")])
    else:
        rows.append(
            [InlineKeyboardButton(text="Заполнить данные", callback_data="profile:start")]
        )
    if profile_flow and profile and not requires_payment:
        rows.append(
            [InlineKeyboardButton(text="Продолжить", callback_data="profile:save")]
        )
    if not is_t0 or profile:
        rows.extend(_global_menu())
    rows.append([InlineKeyboardButton(text="Назад", callback_data="screen:S1")])
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
        f"Расскажите о себе для получения максимального результата \n\n"
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
       
        [InlineKeyboardButton(text="Назад", callback_data="screen:S1")],
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
    rows = [[InlineKeyboardButton(text="Назад", callback_data="screen:S1")]]
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
