from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


FORBIDDEN_WORDS = [
    "нумерология",
    "предназначение",
    "судьба",
    "карма",
    "прогноз",
    "натальный",
    "натальные",
    "натальной",
    "натальных",
]

GUARANTEE_PATTERNS = {
    "guarantee": r"\bгарантир\w*\b",
    "promise": r"\bобеща\w*\b",
    "prediction": r"\bпредсказ\w*\b",
    "forecast": r"\bпрогноз\w*\b",
    "percent": r"\b100\s*%\b|\b100%\b",
    "inevitable": r"\bнеизбежно\b",
    "certainly": r"\bточно\b",
    "mandatory": r"\bобязательно\b",
    "no_doubt": r"\bбез\s+сомнений\b",
}


@dataclass(frozen=True)
class SafetyEvaluation:
    forbidden_words: list[str]
    forbidden_patterns: list[str]

    @property
    def is_safe(self) -> bool:
        return not self.forbidden_words and not self.forbidden_patterns


class ReportSafety:
    def __init__(self) -> None:
        self._word_regexes = {
            word: re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
            for word in FORBIDDEN_WORDS
        }
        self._pattern_regexes = {
            name: re.compile(pattern, re.IGNORECASE)
            for name, pattern in GUARANTEE_PATTERNS.items()
        }

    def evaluate(self, text: str) -> SafetyEvaluation:
        forbidden_words = [
            word for word, regex in self._word_regexes.items() if regex.search(text)
        ]
        forbidden_patterns = [
            name
            for name, regex in self._pattern_regexes.items()
            if regex.search(text)
        ]
        return SafetyEvaluation(
            forbidden_words=forbidden_words,
            forbidden_patterns=forbidden_patterns,
        )

    def build_retry_prompt(self, base_prompt: str, evaluation: SafetyEvaluation) -> str:
        issues: list[str] = []
        if evaluation.forbidden_words:
            issues.append("Запрещённые слова: " + ", ".join(evaluation.forbidden_words))
        if evaluation.forbidden_patterns:
            issues.append(
                "Запрещённые паттерны: "
                + ", ".join(evaluation.forbidden_patterns)
            )
        issues_block = "\n".join(f"- {issue}" for issue in issues) if issues else "- Нарушения правил"

        return (
            f"{base_prompt}\n\n"
            "В предыдущем ответе обнаружены нарушения контент-политики. "
            "Перепиши отчёт заново и строго соблюдай требования:\n"
            "- Полностью исключи запрещённые слова и паттерны гарантий/предсказаний.\n"
            "- Не используй проценты, обещания, гарантии или прогнозы.\n"
            "- Сохраняй нейтральный аналитический стиль.\n"
            f"{issues_block}"
        )

    @staticmethod
    def build_flags(
        *,
        attempts: int,
        history: list[dict[str, Any]],
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        return {
            "provider": provider,
            "model": model,
            "filtered": attempts > 0,
            "attempts": attempts,
            "violations": history,
        }

    @staticmethod
    def evaluation_payload(evaluation: SafetyEvaluation) -> dict[str, Any]:
        return {
            "forbidden_words": evaluation.forbidden_words,
            "forbidden_patterns": evaluation.forbidden_patterns,
            "safe": evaluation.is_safe,
        }


report_safety = ReportSafety()
