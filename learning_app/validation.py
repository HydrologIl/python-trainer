from __future__ import annotations

from typing import Iterable

from learning_app.domain import LOCALLY_GRADED_FORMATS, TaskDraft, TaskFormat
from learning_app.training_profiles import TaskPlan, task_plan_errors


THEORY_FORMATS = {
    TaskFormat.SINGLE_CHOICE,
    TaskFormat.MULTIPLE_CHOICE,
    TaskFormat.TRUE_FALSE,
    TaskFormat.MATCHING,
    TaskFormat.ORDERING,
    TaskFormat.FILL_BLANK,
    TaskFormat.OPEN_ANSWER,
}


def _signature_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def task_signature(task: TaskDraft) -> tuple[str, str, tuple[str, ...]]:
    """Return the content that makes two generated tasks true duplicates."""

    return (
        _signature_text(task.prompt),
        _signature_text(task.stimulus),
        tuple(sorted(_signature_text(option) for option in task.options)),
    )


def duplicate_task_indexes(tasks: Iterable[TaskDraft]) -> list[int]:
    """Return every duplicate position after the first copy of each task."""

    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    duplicates: list[int] = []
    for index, task in enumerate(tasks):
        signature = task_signature(task)
        if signature in seen:
            duplicates.append(index)
        else:
            seen.add(signature)
    return duplicates


def validate_task_batch(
    tasks: Iterable[TaskDraft],
    expected_count: int,
    allowed_knowledge_ids: set[str],
    task_plan: TaskPlan | None = None,
) -> list[TaskDraft]:
    normalized = list(tasks)
    errors: list[str] = []

    if len(normalized) != expected_count:
        errors.append(f"Получено {len(normalized)} заданий вместо {expected_count}.")

    duplicate_indexes = duplicate_task_indexes(normalized)
    if duplicate_indexes:
        task_numbers = ", ".join(str(index + 1) for index in duplicate_indexes)
        errors.append(
            "Найдены полностью повторяющиеся задания: "
            f"{len(duplicate_indexes)} (номера: {task_numbers})."
        )

    if task_plan is not None:
        errors.extend(task_plan_errors(normalized, task_plan))

    for index, task in enumerate(normalized, start=1):
        unknown = set(task.knowledge_client_ids) - allowed_knowledge_ids
        if unknown:
            errors.append(f"Задание {index}: неизвестные knowledge IDs: {sorted(unknown)}.")

        if task.format in {TaskFormat.SINGLE_CHOICE, TaskFormat.MULTIPLE_CHOICE}:
            if len(task.options) < 2:
                errors.append(f"Задание {index}: нужно минимум два варианта ответа.")
            if task.correct_answer is None:
                errors.append(f"Задание {index}: отсутствует правильный ответ.")

        if task.format in {
            TaskFormat.TRUE_FALSE,
            TaskFormat.MATCHING,
            TaskFormat.ORDERING,
            TaskFormat.FILL_BLANK,
        } and task.correct_answer is None:
            errors.append(f"Задание {index}: отсутствует правильный ответ.")

        if task.format in {TaskFormat.DEBUG, TaskFormat.OUTPUT_PREDICTION} and not task.stimulus:
            errors.append(f"Задание {index}: отсутствует код или конфигурация для анализа.")

        if task.format not in LOCALLY_GRADED_FORMATS and not task.answer_guidance:
            errors.append(f"Задание {index}: отсутствуют критерии AI-проверки.")

    if errors:
        raise ValueError("Пакет заданий не прошёл проверку:\n- " + "\n- ".join(errors[:25]))

    return sorted(normalized, key=lambda task: task.difficulty)
