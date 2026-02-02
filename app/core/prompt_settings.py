from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values

from app.db.models import Tariff


PROMPTS_ENV_PATH = Path(".env.prompts")

BASE_SYSTEM_PROMPT = """
Ты — аналитический ассистент. Подготовь структурированный отчёт на русском языке.
Соблюдай нейтральную лексику и используй только допустимые формулировки:
«личные предрасположенности», «навыки и компетенции», «интересы и мотивация»,
«жизненный и профессиональный опыт», «поведенческие паттерны», «ценности»,
«рабочие гипотезы», «варианты сценариев», «зоны роста».
Запрещено использовать слова: «нумерология», «предназначение», «судьба», «карма», «прогноз».
Запрещены обещания результата, гарантии, проценты, «100%». Не давай медицинских, финансовых,
правовых или иных советов из красных зон.
В конце добавь дисклеймеры:
- «Сервис не является консультацией, прогнозом или рекомендацией к действию»
- «Все выводы носят аналитический и описательный характер»
- «Ответственность за решения остаётся за пользователем»
- «Сервис не гарантирует финансовых или иных результатов»
""".strip()

TARIFF_PROMPT_HINTS = {
    Tariff.T0: "Фокус T0: короткий витринный отчёт без детальных разборов.",
    Tariff.T1: "Фокус T1: полный краткий отчёт по структуре T0.",
    Tariff.T2: "Фокус T2: добавь сценарии по деньгам с логикой и проверкой гипотез.",
    Tariff.T3: "Фокус T3: добавь план действий на 1 месяц и 1 год и блок энергия/отношения.",
}

DEFAULT_TARIFF_PROMPTS = {
    tariff: f"{BASE_SYSTEM_PROMPT}\n\n{hint}"
    for tariff, hint in TARIFF_PROMPT_HINTS.items()
}


def _load_prompt_overrides() -> dict[str, str]:
    if not PROMPTS_ENV_PATH.exists():
        return {}
    values = dotenv_values(PROMPTS_ENV_PATH)
    return {key: str(value).strip() for key, value in values.items() if value}


def resolve_tariff_prompt(tariff: Tariff) -> str:
    overrides = _load_prompt_overrides()
    key = f"PROMPT_{tariff.value}"
    return overrides.get(key) or DEFAULT_TARIFF_PROMPTS[tariff]
