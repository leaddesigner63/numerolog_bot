from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import select

from app.db.models import SystemPrompt, Tariff
from app.db.session import get_session_factory


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
Если в facts-pack заполнено поле profile.gender, учитывай его в формулировках без переименования и
без пояснений о наличии/отсутствии этого поля. Если поле пустое, просто пиши нейтрально без
служебных примечаний.
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
    return {key: str(value) if value is not None else "" for key, value in values.items()}


def _load_admin_prompt_overrides() -> dict[str, str]:
    try:
        session_factory = get_session_factory()
    except RuntimeError:
        return {}
    session = session_factory()
    try:
        rows = session.execute(
            select(SystemPrompt).order_by(SystemPrompt.updated_at.desc())
        ).scalars()
        overrides: dict[str, str] = {}
        for prompt in rows:
            if prompt.key not in overrides:
                overrides[prompt.key] = prompt.content
        return overrides
    except Exception:
        return {}
    finally:
        session.close()


def resolve_tariff_prompt(tariff: Tariff) -> str:
    key = f"PROMPT_{tariff.value}"
    admin_overrides = _load_admin_prompt_overrides()
    if admin_overrides:
        return admin_overrides.get(key) or DEFAULT_TARIFF_PROMPTS[tariff]
    file_overrides = _load_prompt_overrides()
    return file_overrides.get(key) or DEFAULT_TARIFF_PROMPTS[tariff]
