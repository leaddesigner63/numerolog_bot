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

RED_ZONE_PATTERNS = {
    "medicine": r"\b(диагноз|лечение|болезн|терапи|лекарств|симптом)\w*\b",
    "finance": r"\b(инвестиц|акц(и|ы)|крипто|трейд|прибыл|доходност|портфел)\w*\b",
    "gambling": r"\b(ставк|казино|лотре|букмекер)\w*\b",
    "drugs": r"\b(наркот|опиат|кокаин|героин|метамфетамин)\w*\b",
    "violence": r"\b(оружи|насили|экстремизм|террор)\w*\b",
    "sexual": r"\b(порн|эротик|секс[-\s]?услуг)\w*\b",
    "self_harm": r"\b(суицид|самоповрежд|самоубийств)\w*\b",
}

SAFE_REFUSAL_TEXT = (
    "Я не могу обсуждать темы, связанные с медициной, финансами, "
    "самоповреждениями, азартными играми или другими запрещёнными зонами. "
    "Могу помочь с аналитическим отчётом: структурировать опыт, сильные стороны, "
    "варианты сценариев и зоны роста в нейтральной форме."
)


@dataclass(frozen=True)
class SafetyEvaluation:
    forbidden_words: list[str]
    forbidden_patterns: list[str]
    red_zones: list[str]

    @property
    def is_safe(self) -> bool:
        return (
            not self.forbidden_words
            and not self.forbidden_patterns
            and not self.red_zones
        )


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
        self._red_zone_regexes = {
            name: re.compile(pattern, re.IGNORECASE)
            for name, pattern in RED_ZONE_PATTERNS.items()
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
        red_zones = [
            name
            for name, regex in self._red_zone_regexes.items()
            if regex.search(text)
        ]
        return SafetyEvaluation(
            forbidden_words=forbidden_words,
            forbidden_patterns=forbidden_patterns,
            red_zones=red_zones,
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
        if evaluation.red_zones:
            issues.append("Красные зоны: " + ", ".join(evaluation.red_zones))
        issues_block = "\n".join(f"- {issue}" for issue in issues) if issues else "- Нарушения правил"

        return (
            f"{base_prompt}\n\n"
            "В предыдущем ответе обнаружены нарушения контент-политики. "
            "Перепиши отчёт заново и строго соблюдай требования:\n"
            "- Полностью исключи запрещённые слова и паттерны гарантий/предсказаний.\n"
            "- Не используй проценты, обещания, гарантии или прогнозы.\n"
            "- Исключи упоминания красных зон (медицина, финансы, самоповреждения и т.п.).\n"
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
        safe_refusal: bool = False,
    ) -> dict[str, Any]:
        return {
            "provider": provider,
            "model": model,
            "filtered": attempts > 0,
            "attempts": attempts,
            "violations": history,
            "safe_refusal": safe_refusal,
        }

    @staticmethod
    def evaluation_payload(evaluation: SafetyEvaluation) -> dict[str, Any]:
        return {
            "forbidden_words": evaluation.forbidden_words,
            "forbidden_patterns": evaluation.forbidden_patterns,
            "red_zones": evaluation.red_zones,
            "safe": evaluation.is_safe,
        }

    @staticmethod
    def build_safe_refusal() -> str:
        return SAFE_REFUSAL_TEXT


report_safety = ReportSafety()
