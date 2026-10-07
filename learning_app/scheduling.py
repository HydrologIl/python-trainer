from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional


REGULAR_REVIEW_DAYS = (1, 3, 7, 14, 30)


@dataclass(frozen=True)
class ReviewSlot:
    kind: str
    scheduled_date: date
    repetition_day: Optional[int] = None
    reason: str = ""

    @property
    def idempotency_suffix(self) -> str:
        day = "none" if self.repetition_day is None else str(self.repetition_day)
        return f"{self.kind}:{day}:{self.scheduled_date.isoformat()}"


def regular_review_slots(learned_date: date) -> list[ReviewSlot]:
    return [
        ReviewSlot(
            kind="regular",
            scheduled_date=learned_date + timedelta(days=day),
            repetition_day=day,
        )
        for day in REGULAR_REVIEW_DAYS
    ]


def due_regular_slots(
    learned_date: date,
    today: date,
    completed_keys: Iterable[str] = (),
) -> list[ReviewSlot]:
    completed = set(completed_keys)
    return [
        slot
        for slot in regular_review_slots(learned_date)
        if slot.scheduled_date <= today and slot.idempotency_suffix not in completed
    ]


def next_regular_slot(
    learned_date: date,
    today: date,
    completed_keys: Iterable[str] = (),
) -> Optional[ReviewSlot]:
    completed = set(completed_keys)
    for slot in regular_review_slots(learned_date):
        if slot.idempotency_suffix not in completed and slot.scheduled_date >= today:
            return slot
    return None


def recovery_slot(error_date: date, reason: str = "weak performance") -> ReviewSlot:
    return ReviewSlot(
        kind="recovery",
        scheduled_date=error_date + timedelta(days=1),
        repetition_day=None,
        reason=reason,
    )


def recovery_task_count(weak_item_count: int) -> int:
    """Keep recovery work in the agreed 15–20 item range."""
    if weak_item_count <= 3:
        return 15
    if weak_item_count <= 6:
        return 18
    return 20
