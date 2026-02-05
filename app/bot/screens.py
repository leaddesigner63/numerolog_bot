from __future__ import annotations

from dataclasses import dataclass
from html import escape as html_escape
import re
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.config import settings


@dataclass(frozen=True)
class ScreenContent:
    messages: list[str]
    keyboard: InlineKeyboardMarkup | None = None
    parse_mode: str | None = None
    image_path: str | None = None


# Единый справочник тарифов (чтобы UI не расходился с логикой оплаты)
TARIFF_META: dict[str, dict[str, Any]] = {
    "T0": {
        "title": "Твоё новое начало",
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
        "title": "В чём твоя сила?",
        "price": 560,
        "bullets": [
            "А ты уже знаешь в чём твоя сила? Ты ярче, чем думаешь. ИИ уже видит твой потенциал. "
            "Он раскроет твои предрасположенности, таланты и зоны роста. "
            "Ты получишь чёткое понимание своих сильных сторон и гипотезы, куда двигаться дальше.🧗‍♀️\n"
            "Жми Старт!💥) Зажги огонь в себе прямо сейчас и раскрой свою силу по настоящему!🔥",
        ],
        "note": None,
    },
    "T2": {
        "title": "Где твои деньги?",
        "price": 2190,
        "bullets": [
            "Беспокоишься о деньгах и будущем? Остынь!😏\n"
            "Здесь ИИ копает намного глубже: Анализирует тебя с упором на доход и моделирует сценарии "
            "твоего будущего. Ты узнаешь, где спрятаны возможности роста дохода, какие повороты возможны в "
            "твоей жизни и как реализовать свои способности на полную.💵 Ты получаешь отчёт с фокусом на деньги!\n"
            "Ну что, приступим к осмыслению своих возможностей?)👨‍💻",
        ],
        "note": None,
    },
    "T3": {
        "title": "Твой путь к себе!",
        "price": 5930,
        "bullets": [
            "А ты знаешь, что можешь достичь большего, но не представляешь, с чего начать? Хватит действовать вслепую — "
            "тебе нужен чёткий план!🗓\n"
            "ИИ составит его специально под тебя.🏋️‍♀️\n"
            "Результат придаст твоей жизни движение вперед к новым победам: ты получишь персональный маршрут с чёткими "
            "шагами, сроками и рекомендациями — что, когда и как делать, чтобы раскрыть свой потенциал и жить по максимуму.🏆\n"
            'Жми "Старт💥" и начни свой путь к Себе!🧘',
        ],
        "note": None,
    },
}


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
                text=_with_button_icons("Оферта", "📄"),
                callback_data="screen:S2",
            ),
            InlineKeyboardButton(
                text=_with_button_icons("Обратная связь", "💬"),
                callback_data="screen:S8",
            ),
        ],
    ]


def _build_keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in rows:
        builder.row(*row)
    return builder.as_markup()


def _with_button_icons(text: str, icon: str) -> str:
    clean_text = text.strip()
    return f"{icon} {clean_text}"


def _format_tariff_label(tariff: str) -> str:
    if tariff == "T0":
        return "Т0"
    return tariff


def _with_screen_prefix(screen_id: str, text: str) -> str:
    if settings.screen_title_enabled:
        return f"{screen_id}: {text.lstrip()}"
    return text.lstrip()


def build_report_wait_message(remaining_seconds: int | None = None, frame: str = "⏳") -> str:
    base_text = "Генерируем отчёт… Пожалуйста, подождите."
    if remaining_seconds is None:
        return _with_screen_prefix("S6", base_text)
    return _with_screen_prefix(
        "S6",
        f"{frame} {base_text}\nОсталось: {remaining_seconds} сек.",
    )


def _common_disclaimer_short() -> str:
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
    meta = TARIFF_META.get(tariff)
    if not meta:
        return ""
    return f"{meta.get('price')} RUB"


def _apply_spoiler_html(text: str, spoiler_text: str) -> str:
    if not spoiler_text:
        return html_escape(text)
    escaped_text = html_escape(text)
    escaped_spoiler = html_escape(spoiler_text)
    spoiler_html = f'<span class="tg-spoiler">{escaped_spoiler}</span>'
    return escaped_text.replace(escaped_spoiler, spoiler_html)


def _render_markdown_bold_as_html(text: str) -> str:
    if not text:
        return ""
    escaped_text = html_escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped_text, flags=re.DOTALL)


def screen_s0(_: dict[str, Any]) -> ScreenContent:
    text = _with_screen_prefix(
        "S0",
        "Бот уже готов разобрать твои данные и показать, в чём твоя сила. 🦾\n"
        "Кстати, в бесплатном превью ты увидишь несколько своих сильных сторон, возможные зоны роста "
        "и структуру полного отчёта. Без мистики и обещаний — только факты и гипотезы. "
        "Хочешь узнать больше?  Жми Далее😎"
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
    text = _with_screen_prefix(
        "S1",
        "ИИ горит весь от нетерпения начать работу. Он не гадает по звёздам, а анализирует реальные данные.  Выбери свой путь с чего начнём!🚀"
    )
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Твоё новое начало (бесплатно)", "🌱"),
                callback_data="tariff:T0",
            ),
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("В чём твоя сила?", "💪"),
                callback_data="tariff:T1",
            ),
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Где твои деньги?", "💰"),
                callback_data="tariff:T2",
            ),
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Твой путь к себе!", "🧭"),
                callback_data="tariff:T3",
            ),
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
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Назад", "↩️"),
                    callback_data="screen:S1",
                )
            ]
        )
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
    parse_mode = None
    if price and price in text:
        text = _apply_spoiler_html(text, price)
        parse_mode = "HTML"

    rows: list[list[InlineKeyboardButton]] = []
    rows.append(
        [
            InlineKeyboardButton(
                text=_with_button_icons("Назад", "↩️"),
                callback_data="screen:S1",
            ),
            InlineKeyboardButton(
                text=_with_button_icons("Старт", "🚀"),
                callback_data="screen:S3",
            ),
        ]
    )
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard, parse_mode=parse_mode)


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
        'Оплачивая, вы подтверждаете согласие с <a href="https://camypau.ru/oferta.html">офертой</a>.'
        f"{order_block}"
    ]
    if not payment_url:
        text_parts.append("\n\nПлатёжная ссылка пока недоступна. Проверьте настройки провайдера.")

    text = _with_screen_prefix("S3", "".join(text_parts))

    rows: list[list[InlineKeyboardButton]] = []
    if payment_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Далее", "💳"),
                    url=payment_url,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=_with_button_icons("Я оплатил(а)", "✅"),
                callback_data="payment:paid",
            ),
            InlineKeyboardButton(
                text=_with_button_icons("Назад", "⬅️"),
                callback_data="screen:S1",
            ),
        ]
    )
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard, parse_mode="HTML")


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
        tariff = report.get("tariff", "—")
        created_at = report.get("created_at", "неизвестно")
        lines.append(f"{index}. Отчёт #{report_id} • {tariff} • {created_at}")
    if total and total > len(reports):
        lines.append(f"\nПоказаны последние {len(reports)} из {total}.")
    return "\n".join(lines)


def _format_questionnaire_profile(questionnaire: dict[str, Any] | None) -> str:
    if not questionnaire:
        return "Профиль расширенной анкеты: нет данных."
    status = questionnaire.get("status", "empty")
    version = questionnaire.get("version", "—")
    answered_count = questionnaire.get("answered_count", 0)
    total_questions = questionnaire.get("total_questions", 0)
    completed_at = questionnaire.get("completed_at") or "не завершена"
    answers = questionnaire.get("answers")
    lines = [
        "Профиль расширенной анкеты:",
        f"Статус: {status}",
        f"Версия: {version}",
        f"Прогресс: {answered_count}/{total_questions}",
        f"Завершена: {completed_at}",
    ]
    if isinstance(answers, dict) and answers:
        lines.append("Ответы:")
        for key, value in answers.items():
            lines.append(f"- {key}: {value}")
    elif answers:
        lines.append(f"Ответы: {answers}")
    else:
        lines.append("Ответы: нет данных.")
    return "\n".join(lines)


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
                "Для изменения данных нажмите «Редактировать»."
            ),
        )
    elif is_t0:
        text = _with_screen_prefix(
            "S4",
            (
                "В превью-отчёте ты увидишь, на что ИИ обратил внимание в первую очередь:"
                "ключевые сильные стороны, возможные зоны роста и формат полного анализа. Коротко и по делу."
                "Начни с малого — дальше решать тебе. Краткий мини отчёт (~30 % полного):"
                "несколько сильных сторон, возможные зоны роста и аккуратная ретроспектива, чтобы оценить подход."
                "Кстати, это честный бесплатный доступ, поэтому можно всего раз в месяц."
                
            ),
        )
    else:
        text = _with_screen_prefix(
            "S4",
            (
                f"Мои данные для тарифа {selected_tariff}.\n\n"
                "Данные ещё не заполнены. Нажмите «Заполнить данные» и следуйте шагам:\n"
                "1) Имя\n"
                "2) Дата рождения (в любом формате)\n"
                "3) Время рождения (в любом формате)\n"
                "4) Место рождения (в любом формате)."
            ),
        )

    rows: list[list[InlineKeyboardButton]] = []
    if profile:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Редактировать", "📝"),
                    callback_data="screen:S4_EDIT",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Удалить мои данные", "🗑️"),
                    callback_data="screen:S4_DELETE",
                )
            ]
        )
    elif is_t0:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Дальше", "➡️"),
                    callback_data="profile:start",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Обратная связь", "💬"),
                    callback_data="screen:S8",
                )
            ]
        )
    elif requires_payment:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("К оплате", "💳"),
                    callback_data="screen:S3",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Тарифы", "🧾"),
                    callback_data="screen:S1",
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Заполнить данные", "📝"),
                    callback_data="profile:start",
                )
            ]
        )
    if profile_flow and profile and not requires_payment:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Продолжить", "▶️"),
                    callback_data="profile:save",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=_with_button_icons("Кабинет", "👤"),
                callback_data="screen:S11",
            )
        ]
    )
    if not is_t0 or profile:
        rows.extend(_global_menu())
    rows.append(
        [
            InlineKeyboardButton(
                text=_with_button_icons("Тарифы", "➡️"),
                callback_data="screen:S1",
            )
        ]
    )
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


def screen_s4_delete_confirm(_: dict[str, Any]) -> ScreenContent:
    text = _with_screen_prefix(
        "S4",
        (
            "Вы уверены, что хотите удалить все ваши данные?\n"
            "Профиль, отчёты, анкеты и история платежей будут удалены, "
            "а учётная запись останется."
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
    progress_line = ""
    if total_questions:
        progress_line = f"Прогресс: {answered_count}/{total_questions}."

    text = _with_screen_prefix(
        "S5",
        f"Для получения максимального результата заполните, пожалуйста, анкету✍️ \n\n"
        " Опыт и проекты\n"
        " Навыки (шкала 1–5)\n"
        " Интересы и мотивация\n"
        " Ограничения (время/ресурсы)\n"
        " Цели\n\n"
        f"{progress_line}"
    ).strip()

    rows: list[list[InlineKeyboardButton]] = []
    if status == "completed":
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Редактировать анкету", "📝"),
                    callback_data="questionnaire:edit",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Редактировать данные", "📝"),
                    callback_data="screen:S4",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Готово", "✅"),
                    callback_data="questionnaire:done",
                )
            ]
        )
    else:
        button_text = "Продолжить анкету" if answered_count else "Заполнить анкету"
        button_icon = "▶️" if answered_count else "📝"
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons(button_text, button_icon),
                    callback_data="questionnaire:start",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=_with_button_icons("Назад", "↩️"),
                callback_data="screen:S1",
            )
        ]
    )
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


def screen_s6(_: dict[str, Any]) -> ScreenContent:
    text = build_report_wait_message()
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Назад в тарифы", "↩️"),
                callback_data="screen:S1",
            )
        ],
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
       
    )
    disclaimer_html = html_escape(disclaimer)
    if report_text:
        report_html = _render_markdown_bold_as_html(report_text)
        text = _with_screen_prefix("S7", f"{report_html}\n\n{disclaimer_html}")
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
            InlineKeyboardButton(
                text=_with_button_icons("Продолжить", "➡️"),
                callback_data="screen:S1",
            )
        ],
        *_global_menu(),
    ]
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard, parse_mode="HTML")


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
            InlineKeyboardButton(
                text=_with_button_icons("Отправить", "📤"),
                callback_data="feedback:send",
            )
        ],
        [
            InlineKeyboardButton(
                text=_with_button_icons("Тарифы", "🧾"),
                callback_data="screen:S1",
            )
        ],
    ]
    if settings.feedback_group_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_with_button_icons("Перейти в группу", "👥"),
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
        reports_line = f"\n\nСохранённых отчётов: {reports_total}."
    questionnaire_text = _format_questionnaire_profile(state.get("questionnaire"))

    if profile:
        text = _with_screen_prefix(
            "S11",
            (
                "Личный кабинет.\n\n"
                f"Имя: {profile.get('name')}\n"
                f"Дата рождения: {profile.get('birth_date')}\n"
                f"Время рождения: {birth_time}\n"
                f"Место рождения: {birth_place}"
                f"{reports_line}\n\n{questionnaire_text}"
            ),
        )
    else:
        text = _with_screen_prefix(
            "S11",
            "Личный кабинет.\n\nДанные профиля ещё не заполнены."
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
                text=_with_button_icons("Тарифы", "🧾"),
                callback_data="screen:S1",
            )
        ],
        *(_global_menu()),
    ]
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
    report_text = (state.get("report_text") or "").strip()
    report_meta = state.get("report_meta") or {}
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
    disclaimer_html = html_escape(disclaimer)
    header = html_escape(
        (
            f"Отчёт #{report_id}\n"
            f"Тариф: {report_tariff}\n"
            f"Дата: {report_created_at}\n\n"
        )
    )
    if report_text:
        report_html = _render_markdown_bold_as_html(report_text)
        text = _with_screen_prefix("S13", f"{header}{report_html}\n\n{disclaimer_html}")
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
    return ScreenContent(messages=[text], keyboard=keyboard, parse_mode="HTML")


def screen_s14(state: dict[str, Any]) -> ScreenContent:
    report_meta = state.get("report_meta") or {}
    report_id = report_meta.get("id", "—")
    text = _with_screen_prefix(
        "S14",
        f"Удалить отчёт #{report_id}? Это действие нельзя отменить.",
    )
    rows = [
        [
            InlineKeyboardButton(
                text=_with_button_icons("Удалить", "✅"),
                callback_data="report:delete:confirm",
            ),
            InlineKeyboardButton(
                text=_with_button_icons("Отмена", "❌"),
                callback_data="screen:S13",
            ),
        ],
    ]
    rows.extend(_global_menu())
    keyboard = _build_keyboard(rows)
    return ScreenContent(messages=[text], keyboard=keyboard)


SCREEN_REGISTRY = {
    "S0": screen_s0,
    "S1": screen_s1,
    "S2": screen_s2,
    "S3": screen_s3,
    "S4": screen_s4,
    "S4_EDIT": screen_s4_edit,
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
}
