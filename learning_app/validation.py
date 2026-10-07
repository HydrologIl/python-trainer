from __future__ import annotations

from collections import Counter
from typing import Iterable

from learning_app.domain import LOCALLY_GRADED_FORMATS, TaskDraft, TaskFormat


THEORY_FORMATS = {
    TaskFormat.SINGLE_CHOICE,
    TaskFormat.MULTIPLE_CHOICE,
    TaskFormat.TRUE_FALSE,
    TaskFormat.MATCHING,
    TaskFormat.ORDERING,
    TaskFormat.FILL_BLANK,
    TaskFormat.OPEN_ANSWER,
}


def validate_task_batch(
    tasks: Iterable[TaskDraft],
    expected_count: int,
    allowed_knowledge_ids: set[str],
) -> list[TaskDraft]:
    normalized = list(tasks)
    errors: list[str] = []

    if len(normalized) != expected_count:
        errors.append(f"Получено {len(normalized)} заданий вместо {expected_count}.")

    prompts = Counter(task.prompt.strip().casefold() for task in normalized)
    duplicate_prompts = [prompt for prompt, count in prompts.items() if count > 1]
    if duplicate_prompts:
        errors.append(f"Найдены повторяющиеся условия: {len(duplicate_prompts)}.")

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
