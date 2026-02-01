from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import logging
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
    start_question_id: str | None
    questions: dict[str, QuestionnaireQuestion]

    def get_question(self, question_id: str | None) -> QuestionnaireQuestion | None:
        if not question_id:
            return None
        question = self.questions.get(question_id)
        if not question:
            logging.getLogger(__name__).warning(
                "questionnaire_question_missing",
                extra={"question_id": question_id},
            )
        return question


@lru_cache(maxsize=1)
def load_questionnaire_config() -> QuestionnaireConfig:
    config_path = Path(__file__).with_name("questionnaire_v1.json")
    raw = json.loads(config_path.read_text(encoding="utf-8"))

    logger = logging.getLogger(__name__)
    allowed_types = {"text", "choice", "scale"}
    questions: dict[str, QuestionnaireQuestion] = {}
    for question in raw.get("questions", []):
        question_id = str(question.get("id") or "").strip()
        question_type = str(question.get("type") or "").strip()
        if not question_id or question_type not in allowed_types:
            logger.warning(
                "questionnaire_invalid_question",
                extra={"question_id": question_id, "question_type": question_type},
            )
            continue
        text = str(question.get("text") or "").strip()
        if not text:
            logger.warning(
                "questionnaire_question_text_missing",
                extra={"question_id": question_id},
            )
            continue
        options = question.get("options") or []
        scale = question.get("scale") if question_type == "scale" else None
        if question_type == "choice":
            if not isinstance(options, list):
                logger.warning(
                    "questionnaire_options_invalid",
                    extra={"question_id": question_id},
                )
                options = []
        if question_type == "scale":
            if not isinstance(scale, dict):
                logger.warning(
                    "questionnaire_scale_invalid",
                    extra={"question_id": question_id},
                )
                scale = {"min": 1, "max": 5, "labels": {}}
        transitions = question.get("transitions") or {}
        if not isinstance(transitions, dict):
            logger.warning(
                "questionnaire_transitions_invalid",
                extra={"question_id": question_id},
            )
            transitions = {}
        questions[question_id] = QuestionnaireQuestion(
            question_id=question_id,
            question_type=question_type,
            text=text,
            required=bool(question.get("required", False)),
            options=options,
            scale=scale,
            next_question_id=question.get("next"),
            transitions=transitions,
        )

    start_question_id = raw.get("start_question_id")
    if start_question_id not in questions:
        if questions:
            logger.warning(
                "questionnaire_start_question_invalid",
                extra={"start_question_id": start_question_id},
            )
            start_question_id = next(iter(questions.keys()))
        else:
            logger.warning("questionnaire_empty")
            start_question_id = None

    return QuestionnaireConfig(
        version=raw.get("version", "unknown"),
        start_question_id=start_question_id,
        questions=questions,
    )


def resolve_next_question_id(question: QuestionnaireQuestion, answer: Any) -> str | None:
    if question.transitions:
        answer_key = str(answer)
        if answer_key in question.transitions:
            return question.transitions[answer_key]
    return question.next_question_id
