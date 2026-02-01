from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class QuestionnaireQuestion:
    question_id: str
    question_type: str
    text: str
    required: bool
    options: list[dict[str, str]]
    scale: dict[str, Any] | None
    next_question_id: str | None
    transitions: dict[str, str]


@dataclass(frozen=True)
class QuestionnaireConfig:
    version: str
    start_question_id: str
    questions: dict[str, QuestionnaireQuestion]

    def get_question(self, question_id: str) -> QuestionnaireQuestion:
        if question_id not in self.questions:
            raise KeyError(f"Unknown question id: {question_id}")
        return self.questions[question_id]


@lru_cache(maxsize=1)
def load_questionnaire_config() -> QuestionnaireConfig:
    config_path = Path(__file__).with_name("questionnaire_v1.json")
    raw = json.loads(config_path.read_text(encoding="utf-8"))

    questions: dict[str, QuestionnaireQuestion] = {}
    for question in raw.get("questions", []):
        question_id = question["id"]
        questions[question_id] = QuestionnaireQuestion(
            question_id=question_id,
            question_type=question["type"],
            text=question["text"],
            required=bool(question.get("required", False)),
            options=question.get("options", []),
            scale=question.get("scale"),
            next_question_id=question.get("next"),
            transitions=question.get("transitions", {}),
        )

    return QuestionnaireConfig(
        version=raw["version"],
        start_question_id=raw["start_question_id"],
        questions=questions,
    )


def resolve_next_question_id(question: QuestionnaireQuestion, answer: Any) -> str | None:
    if question.transitions:
        answer_key = str(answer)
        if answer_key in question.transitions:
            return question.transitions[answer_key]
    return question.next_question_id
