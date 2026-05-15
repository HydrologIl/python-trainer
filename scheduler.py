from datetime import date, datetime, timedelta
from typing import Any


REPETITION_DAYS = [1, 3, 7, 14, 30]
ACTIVE_STATUSES = {"active", "learned"}


def parse_date(value) -> date | None:
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    for date_format in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    return None


def get_repetition_info(topic: dict[str, Any], today: date) -> dict[str, Any] | None:
    """Backward-compatible helper: returns only repetitions due exactly today."""
    status = topic.get("status")
    learned_date_value = topic.get("learned_date")

    if status not in ACTIVE_STATUSES or not learned_date_value:
        return None

    learned_date = parse_date(learned_date_value)

    if not learned_date:
        return None

    days_after_learning = (today - learned_date).days

    if days_after_learning in REPETITION_DAYS:
        return {
            "topic": topic,
            "repetition_day": days_after_learning,
            "learned_date": learned_date,
            "scheduled_date": today,
            "days_overdue": 0,
            "is_overdue": False,
        }

    return None


def get_today_repetitions(
    topics: list[dict[str, Any]],
    today: date,
) -> list[dict[str, Any]]:
    repetitions = []

    for topic in topics:
        repetition_info = get_repetition_info(topic, today)
        if repetition_info:
            repetitions.append(repetition_info)

    return repetitions


def _is_repetition_completed(
    sessions: list[dict[str, Any]] | None,
    topic_id: str,
    repetition_day: int,
    scheduled_date: date,
) -> bool:
    if not sessions:
        return False

    scheduled_date_str = scheduled_date.isoformat()

    for session in sessions:
        if (
            session.get("topic_id") == topic_id
            and session.get("repetition_day") == repetition_day
            and session.get("scheduled_date") == scheduled_date_str
            and session.get("status") == "completed"
        ):
            return True

    return False


def get_due_repetitions(
    topics: list[dict[str, Any]],
    today: date,
    sessions: list[dict[str, Any]] | None = None,
    include_completed: bool = False,
) -> list[dict[str, Any]]:
    """
    Returns repetitions that are due today or overdue.

    A repetition is considered overdue when its scheduled Ebbinghaus date has
    already passed and there is no completed session for this exact topic,
    repetition day and scheduled date.
    """
    due_items: list[dict[str, Any]] = []

    for topic in topics:
        if topic.get("status") not in ACTIVE_STATUSES or not topic.get("learned_date"):
            continue

        learned_date = parse_date(topic["learned_date"])

        if not learned_date:
            continue

        for repetition_day in REPETITION_DAYS:
            scheduled_date = learned_date + timedelta(days=repetition_day)

            if scheduled_date > today:
                continue

            if not include_completed and _is_repetition_completed(
                sessions,
                topic.get("id", ""),
                repetition_day,
                scheduled_date,
            ):
                continue

            days_overdue = (today - scheduled_date).days
            due_items.append(
                {
                    "topic": topic,
                    "repetition_day": repetition_day,
                    "learned_date": learned_date,
                    "scheduled_date": scheduled_date,
                    "days_overdue": days_overdue,
                    "is_overdue": days_overdue > 0,
                }
            )

    return sorted(
        due_items,
        key=lambda item: (
            item["scheduled_date"],
            item["topic"].get("block", 0),
            item["topic"].get("title", ""),
        ),
    )


def get_next_repetition(topic: dict[str, Any], today: date) -> str:
    learned_date_value = topic.get("learned_date", "")
    status = topic.get("status", "planned")

    if status == "planned":
        return "тема ещё не отмечена как пройденная"

    if status in ["completed", "archived"]:
        return "тема закрыта"

    if status == "paused":
        return "тема на паузе"

    if not learned_date_value:
        return "дата изучения не указана"

    learned_date = parse_date(learned_date_value)

    if not learned_date:
        return "дата изучения указана в неизвестном формате"

    days_passed = (today - learned_date).days

    if days_passed < 0:
        return f"изучение запланировано на {learned_date.isoformat()}"

    for repetition_day in REPETITION_DAYS:
        if repetition_day >= days_passed:
            next_date = learned_date + timedelta(days=repetition_day)
            return f"день {repetition_day}: {next_date.isoformat()}"

    return "все повторения по этой теме пройдены"


def get_upcoming_repetitions(
    topics: list[dict[str, Any]],
    today: date,
    horizon_days: int = 7,
    days_ahead: int | None = None,
) -> list[dict[str, Any]]:
    # days_ahead is kept for backward compatibility with older UI calls.
    if days_ahead is not None:
        horizon_days = days_ahead

    upcoming = []

    for topic in topics:
        if topic.get("status") not in ACTIVE_STATUSES or not topic.get("learned_date"):
            continue

        learned_date = parse_date(topic["learned_date"])

        if not learned_date:
            continue

        for repetition_day in REPETITION_DAYS:
            repetition_date = learned_date + timedelta(days=repetition_day)

            if today <= repetition_date <= today + timedelta(days=horizon_days):
                upcoming.append(
                    {
                        "date": repetition_date,
                        "days_from_today": (repetition_date - today).days,
                        "topic": topic,
                        "repetition_day": repetition_day,
                    }
                )

    return sorted(upcoming, key=lambda item: item["date"])
