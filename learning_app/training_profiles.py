from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from learning_app.domain import KnowledgeKind, TaskDraft, TaskFormat


THEORY_GROUP = "theory"
ANALYSIS_GROUP = "analysis"
CREATION_GROUP = "creation"
GROUP_ORDER = (CREATION_GROUP, ANALYSIS_GROUP, THEORY_GROUP)

FORMAT_GROUPS: dict[TaskFormat, str] = {
    TaskFormat.SINGLE_CHOICE: THEORY_GROUP,
    TaskFormat.MULTIPLE_CHOICE: THEORY_GROUP,
    TaskFormat.TRUE_FALSE: THEORY_GROUP,
    TaskFormat.MATCHING: THEORY_GROUP,
    TaskFormat.ORDERING: THEORY_GROUP,
    TaskFormat.FILL_BLANK: THEORY_GROUP,
    TaskFormat.OPEN_ANSWER: THEORY_GROUP,
    TaskFormat.DEBUG: ANALYSIS_GROUP,
    TaskFormat.OUTPUT_PREDICTION: ANALYSIS_GROUP,
    TaskFormat.WRITE_CODE: CREATION_GROUP,
    TaskFormat.WRITE_CONFIG: CREATION_GROUP,
    TaskFormat.PRACTICAL_OPEN: CREATION_GROUP,
}

GROUP_LABELS = {
    CREATION_GROUP: "Создание",
    ANALYSIS_GROUP: "Анализ",
    THEORY_GROUP: "Теория",
}

FORMAT_LABELS = {
    TaskFormat.SINGLE_CHOICE.value: "Один вариант ответа",
    TaskFormat.MULTIPLE_CHOICE.value: "Несколько вариантов",
    TaskFormat.TRUE_FALSE.value: "Верно / неверно",
    TaskFormat.MATCHING.value: "Сопоставление",
    TaskFormat.ORDERING.value: "Порядок действий",
    TaskFormat.FILL_BLANK.value: "Заполнение пропуска",
    TaskFormat.OPEN_ANSWER.value: "Открытый теоретический ответ",
    TaskFormat.DEBUG.value: "Найти и исправить ошибку",
    TaskFormat.OUTPUT_PREDICTION.value: "Определить результат",
    TaskFormat.WRITE_CODE.value: "Написать код",
    TaskFormat.WRITE_CONFIG.value: "Написать конфигурацию",
    TaskFormat.PRACTICAL_OPEN.value: "Практическое решение",
}

PROFILE_LABELS = {
    "auto": "Автоматический",
    "practical": "Практический",
    "balanced": "Сбалансированный",
    "theoretical": "Теоретический",
    "python_practice": "Кодинг: 10 / 10 / 20",
    "custom": "Собственный",
}

PROFILE_DESCRIPTIONS = {
    "auto": "Состав определяется по соотношению знаний и навыков в модуле.",
    "practical": "50% создание, 25% анализ, 25% теория.",
    "balanced": "35% создание, 30% анализ, 35% теория.",
    "theoretical": "15% создание, 25% анализ, 60% теория.",
    "python_practice": "25% исправление, 25% результат кода, 50% написание кода.",
    "custom": "Свои пропорции групп и разрешённые форматы.",
}

PROFILE_KEYS = tuple(PROFILE_LABELS)

DEFAULT_CUSTOM_CONFIG: dict[str, Any] = {
    "group_weights": {
        CREATION_GROUP: 50,
        ANALYSIS_GROUP: 25,
        THEORY_GROUP: 25,
    },
    "allowed_formats": [task_format.value for task_format in TaskFormat],
}

_PROFILE_WEIGHTS = {
    "practical": {CREATION_GROUP: 50, ANALYSIS_GROUP: 25, THEORY_GROUP: 25},
    "balanced": {CREATION_GROUP: 35, ANALYSIS_GROUP: 30, THEORY_GROUP: 35},
    "theoretical": {CREATION_GROUP: 15, ANALYSIS_GROUP: 25, THEORY_GROUP: 60},
}


@dataclass(frozen=True)
class TaskPlan:
    profile_key: str
    profile_label: str
    task_count: int
    group_counts: dict[str, int]
    format_counts: dict[str, int]
    allowed_formats: tuple[str, ...]

    def to_prompt_data(self) -> dict[str, Any]:
        return {
            "profile": self.profile_key,
            "profile_label": self.profile_label,
            "task_count": self.task_count,
            "group_counts": self.group_counts,
            "format_counts": self.format_counts,
            "allowed_formats": list(self.allowed_formats),
            "format_groups": {
                task_format: FORMAT_GROUPS[TaskFormat(task_format)]
                for task_format in self.allowed_formats
            },
        }


def formats_for_group(group: str) -> list[str]:
    return [
        task_format.value
        for task_format, format_group in FORMAT_GROUPS.items()
        if format_group == group
    ]


def normalize_custom_config(config: dict[str, Any] | None) -> dict[str, Any]:
    source = config or {}
    source_weights = source.get("group_weights") or {}
    weights = {
        group: max(
            0,
            int(
                source_weights.get(
                    group,
                    DEFAULT_CUSTOM_CONFIG["group_weights"][group],
                )
            ),
        )
        for group in GROUP_ORDER
    }
    if sum(weights.values()) <= 0:
        weights = dict(DEFAULT_CUSTOM_CONFIG["group_weights"])

    requested_formats = source.get("allowed_formats")
    known_formats = {task_format.value for task_format in TaskFormat}
    if requested_formats is None:
        allowed = list(DEFAULT_CUSTOM_CONFIG["allowed_formats"])
    else:
        allowed = [str(value) for value in requested_formats if str(value) in known_formats]

    return {"group_weights": weights, "allowed_formats": allowed}


def custom_config_errors(config: dict[str, Any]) -> list[str]:
    normalized = normalize_custom_config(config)
    errors: list[str] = []
    if sum(normalized["group_weights"].values()) != 100:
        errors.append("Сумма долей групп должна быть равна 100%.")
    for group, weight in normalized["group_weights"].items():
        if weight <= 0:
            continue
        if not any(
            value in formats_for_group(group)
            for value in normalized["allowed_formats"]
        ):
            errors.append(
                f"Для группы «{GROUP_LABELS[group]}» выбран ненулевой процент, "
                "но не разрешён ни один формат."
            )
    return errors


def _allocate_counts(weights: dict[str, int], total: int) -> dict[str, int]:
    positive = {key: max(0, int(value)) for key, value in weights.items()}
    weight_sum = sum(positive.values())
    if total <= 0 or weight_sum <= 0:
        return {key: 0 for key in positive}

    exact = {key: total * value / weight_sum for key, value in positive.items()}
    counts = {key: int(value) for key, value in exact.items()}
    remainder = total - sum(counts.values())
    ranked = sorted(
        positive,
        key=lambda key: (exact[key] - counts[key], positive[key]),
        reverse=True,
    )
    for key in ranked[:remainder]:
        counts[key] += 1
    return counts


def _auto_profile(knowledge_kinds: Iterable[str]) -> str:
    kinds = [str(kind) for kind in knowledge_kinds]
    if not kinds:
        return "balanced"
    skill_count = sum(kind == KnowledgeKind.SKILL.value for kind in kinds)
    skill_ratio = skill_count / len(kinds)
    if skill_ratio >= 0.65:
        return "practical"
    if skill_ratio <= 0.35:
        return "theoretical"
    return "balanced"


def build_task_plan(
    profile_key: str,
    task_count: int,
    knowledge_kinds: Iterable[str],
    custom_config: dict[str, Any] | None = None,
) -> TaskPlan:
    if profile_key not in PROFILE_LABELS:
        profile_key = "auto"

    if profile_key == "python_practice":
        format_counts = _allocate_counts(
            {
                TaskFormat.DEBUG.value: 25,
                TaskFormat.OUTPUT_PREDICTION.value: 25,
                TaskFormat.WRITE_CODE.value: 50,
            },
            task_count,
        )
        group_counts = {
            CREATION_GROUP: format_counts[TaskFormat.WRITE_CODE.value],
            ANALYSIS_GROUP: (
                format_counts[TaskFormat.DEBUG.value]
                + format_counts[TaskFormat.OUTPUT_PREDICTION.value]
            ),
            THEORY_GROUP: 0,
        }
        return TaskPlan(
            profile_key=profile_key,
            profile_label=PROFILE_LABELS[profile_key],
            task_count=task_count,
            group_counts=group_counts,
            format_counts=format_counts,
            allowed_formats=tuple(format_counts),
        )

    actual_profile = (
        _auto_profile(knowledge_kinds) if profile_key == "auto" else profile_key
    )
    if actual_profile == "custom":
        config = normalize_custom_config(custom_config)
        errors = custom_config_errors(config)
        if errors:
            raise ValueError(" ".join(errors))
        weights = config["group_weights"]
        allowed_formats = tuple(config["allowed_formats"])
        label = PROFILE_LABELS[profile_key]
    else:
        weights = _PROFILE_WEIGHTS.get(actual_profile, _PROFILE_WEIGHTS["balanced"])
        allowed_formats = tuple(task_format.value for task_format in TaskFormat)
        label = PROFILE_LABELS[profile_key]
        if profile_key == "auto":
            label += f" → {PROFILE_LABELS[actual_profile]}"

    group_counts = _allocate_counts(weights, task_count)
    return TaskPlan(
        profile_key=profile_key,
        profile_label=label,
        task_count=task_count,
        group_counts=group_counts,
        format_counts={},
        allowed_formats=allowed_formats,
    )


def select_tasks_for_plan(
    tasks: Iterable[TaskDraft],
    plan: TaskPlan,
    excluded_indexes: set[int] | None = None,
) -> tuple[list[TaskDraft], TaskPlan]:
    excluded = excluded_indexes or set()
    accepted: list[TaskDraft] = []
    used: Counter[str] = Counter()
    limits = plan.format_counts or plan.group_counts

    for index, task in enumerate(tasks):
        if index in excluded or task.format.value not in plan.allowed_formats:
            continue
        bucket = (
            task.format.value
            if plan.format_counts
            else FORMAT_GROUPS.get(task.format, "")
        )
        if not bucket or used[bucket] >= limits.get(bucket, 0):
            continue
        used[bucket] += 1
        accepted.append(task)

    missing = {
        key: value - used[key]
        for key, value in limits.items()
        if value > used[key]
    }
    if plan.format_counts:
        remaining_format_counts = missing
        remaining_group_counts = {
            group: sum(
                count
                for task_format, count in missing.items()
                if FORMAT_GROUPS[TaskFormat(task_format)] == group
            )
            for group in GROUP_ORDER
        }
        remaining_allowed = tuple(missing)
    else:
        remaining_format_counts = {}
        remaining_group_counts = missing
        remaining_allowed = plan.allowed_formats

    remaining = TaskPlan(
        profile_key=plan.profile_key,
        profile_label=plan.profile_label,
        task_count=sum(missing.values()),
        group_counts=remaining_group_counts,
        format_counts=remaining_format_counts,
        allowed_formats=remaining_allowed,
    )
    return accepted, remaining


def task_plan_errors(tasks: Iterable[TaskDraft], plan: TaskPlan) -> list[str]:
    rows = list(tasks)
    errors: list[str] = []
    disallowed = Counter(
        task.format.value for task in rows if task.format.value not in plan.allowed_formats
    )
    if disallowed:
        errors.append(f"Недопустимые форматы: {dict(disallowed)}.")

    if plan.format_counts:
        actual = Counter(task.format.value for task in rows)
        if dict(actual) != plan.format_counts:
            errors.append(
                f"Состав по форматам {dict(actual)} не совпадает с планом "
                f"{plan.format_counts}."
            )
    else:
        actual_groups = Counter(FORMAT_GROUPS.get(task.format, "unknown") for task in rows)
        if {group: actual_groups[group] for group in GROUP_ORDER} != plan.group_counts:
            errors.append(
                "Состав по группам "
                f"{dict(actual_groups)} не совпадает с планом {plan.group_counts}."
            )
    return errors


def task_plan_summary(plan: TaskPlan) -> str:
    if plan.format_counts:
        return " · ".join(
            f"{FORMAT_LABELS[task_format]} — {count}"
            for task_format, count in plan.format_counts.items()
            if count
        )
    return " · ".join(
        f"{GROUP_LABELS[group]} — {plan.group_counts.get(group, 0)}"
        for group in GROUP_ORDER
        if plan.group_counts.get(group, 0)
    )
