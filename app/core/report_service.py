from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from app.core.llm_router import LLMResponse, LLMUnavailableError, llm_router


SYSTEM_PROMPT = """
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


class ReportService:
    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    async def generate_report(self, *, user_id: int, state: dict[str, Any]) -> LLMResponse | None:
        facts_pack = {
            "user_id": user_id,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "tariff": state.get("selected_tariff"),
            "profile": state.get("profile"),
            "questionnaire": state.get("questionnaire"),
        }

        try:
            return await asyncio.to_thread(llm_router.generate, facts_pack, SYSTEM_PROMPT)
        except LLMUnavailableError:
            self._logger.warning("llm_unavailable", extra={"user_id": user_id})
            return None


report_service = ReportService()
