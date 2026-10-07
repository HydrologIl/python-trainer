from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from math import exp
from typing import Any, Iterable


VERDICT_VALUE = {
    "correct": 1.0,
    "partially_correct": 0.45,
    "incorrect": 0.0,
}


@dataclass(frozen=True)
class MasterySummary:
    knowledge_id: str
    score: float
    attempts: int
    recent_errors: tuple[str, ...]


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return datetime.min


def calculate_mastery(
    attempts: Iterable[dict[str, Any]],
    initial_score: float = 0.5,
) -> dict[str, MasterySummary]:
    """Calculate recency-weighted mastery per knowledge item.

    The newest attempt carries the most weight, while older evidence still
    contributes. This is intentionally transparent and can be replaced later
    without changing persisted attempt history.
    """

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        for knowledge_id in attempt.get("knowledge_ids", []):
            grouped[str(knowledge_id)].append(attempt)

    result: dict[str, MasterySummary] = {}
    for knowledge_id, rows in grouped.items():
        ordered = sorted(rows, key=lambda row: _parse_timestamp(row.get("created_at")))
        weighted_sum = initial_score * 0.75
        total_weight = 0.75
        errors: list[str] = []

        for age, row in enumerate(reversed(ordered)):
            weight = exp(-0.35 * age)
            value = VERDICT_VALUE.get(str(row.get("verdict", "")), 0.0)
            weighted_sum += value * weight
            total_weight += weight
            error = str(row.get("error_type") or row.get("error_summary") or "").strip()
            if value < 1.0 and error and error not in errors and len(errors) < 5:
                errors.append(error)

        result[knowledge_id] = MasterySummary(
            knowledge_id=knowledge_id,
            score=round(max(0.0, min(1.0, weighted_sum / total_weight)), 3),
            attempts=len(ordered),
            recent_errors=tuple(errors),
        )

    return result


def generation_weight(mastery: float, attempts: int) -> float:
    """Prioritize weak areas while retaining broad module coverage."""
    bounded = max(0.0, min(1.0, mastery))
    uncertainty_bonus = 0.35 if attempts == 0 else 0.0
    return round(0.35 + (1.0 - bounded) * 1.65 + uncertainty_bonus, 3)


def needs_recovery(
    verdicts: Iterable[str],
    incorrect_threshold: int = 2,
) -> bool:
    values = list(verdicts)
    incorrect = sum(value == "incorrect" for value in values)
    partial = sum(value == "partially_correct" for value in values)
    return incorrect >= incorrect_threshold or (incorrect + partial) >= 3
