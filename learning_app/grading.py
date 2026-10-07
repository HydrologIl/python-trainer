from __future__ import annotations

import json
import re
from typing import Any, Optional

from learning_app.domain import GradingResult, TaskFormat, Verdict


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return re.sub(r"\s+", " ", text)


def _as_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("[", "{")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def grade_locally(
    task_format: str,
    correct_answer: Any,
    user_answer: Any,
) -> Optional[GradingResult]:
    """Return a deterministic grade, or None when AI grading is required."""

    try:
        fmt = TaskFormat(task_format)
    except ValueError:
        return None

    correct = _as_value(correct_answer)
    answer = _as_value(user_answer)

    if fmt in {TaskFormat.SINGLE_CHOICE, TaskFormat.FILL_BLANK}:
        is_correct = _normalize_text(correct) == _normalize_text(answer)
    elif fmt == TaskFormat.TRUE_FALSE:
        truthy = {"true", "1", "да", "верно", "истина"}
        falsy = {"false", "0", "нет", "неверно", "ложь"}

        def truth_value(value: Any) -> Optional[bool]:
            normalized = _normalize_text(value)
            if normalized in truthy:
                return True
            if normalized in falsy:
                return False
            return None

        is_correct = truth_value(correct) is not None and truth_value(correct) == truth_value(answer)
    elif fmt == TaskFormat.MULTIPLE_CHOICE:
        if not isinstance(correct, list) or not isinstance(answer, list):
            is_correct = False
        else:
            is_correct = {_normalize_text(item) for item in correct} == {
                _normalize_text(item) for item in answer
            }
    elif fmt == TaskFormat.ORDERING:
        if not isinstance(correct, list) or not isinstance(answer, list):
            is_correct = False
        else:
            is_correct = [_normalize_text(item) for item in correct] == [
                _normalize_text(item) for item in answer
            ]
    elif fmt == TaskFormat.MATCHING:
        if not isinstance(correct, dict) or not isinstance(answer, dict):
            is_correct = False
        else:
            normalized_correct = {
                _normalize_text(key): _normalize_text(value) for key, value in correct.items()
            }
            normalized_answer = {
                _normalize_text(key): _normalize_text(value) for key, value in answer.items()
            }
            is_correct = normalized_correct == normalized_answer
    else:
        return None

    return GradingResult(
        verdict=Verdict.CORRECT if is_correct else Verdict.INCORRECT,
        feedback="Верно." if is_correct else "Ответ не совпадает с правильным вариантом.",
        error_type="" if is_correct else "theory_recall_error",
        error_summary="" if is_correct else "Неверно воспроизведён теоретический материал.",
    )
