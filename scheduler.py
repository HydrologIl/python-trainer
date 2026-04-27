from datetime import date, datetime, timedelta
from typing import Any


REPETITION_DAYS = [1, 3, 7, 14, 30]


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def get_repetition_info(topic: dict[str, Any], today: date) -> dict[str, Any] | None:
    status = topic.get("status")
    learned_date_value = topic.get("learned_date")

    if status != "active" or not learned_date_value:
        return None

    learned_date = parse_date(learned_date_value)
    days_after_learning = (today - learned_date).days

    if days_after_learning in REPETITION_DAYS:
        return {
            "topic": topic,
            "repetition_day": days_after_learning,
            "learned_date": learned_date,
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


def get_next_repetition(topic: dict[str, Any], today: date) -> str:
    learned_date_value = topic.get("learned_date", "")
    status = topic.get("status", "planned")

    if status == "planned":
        return "тема ещё не отмечена как пройденная"

    if status == "completed":
        return "тема закрыта"

    if status == "paused":
        return "тема на паузе"

    if not learned_date_value:
        return "дата изучения не указана"

    learned_date = parse_date(learned_date_value)
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
) -> list[dict[str, Any]]:
    upcoming = []

    for topic in topics:
        if topic.get("status") != "active" or not topic.get("learned_date"):
            continue

        learned_date = parse_date(topic["learned_date"])

        for repetition_day in REPETITION_DAYS:
            repetition_date = learned_date + timedelta(days=repetition_day)

            if today <= repetition_date <= today + timedelta(days=horizon_days):
                upcoming.append(
                    {
                        "date": repetition_date,
                        "topic": topic,
                        "repetition_day": repetition_day,
                    }
                )

    return sorted(upcoming, key=lambda item: item["date"])
