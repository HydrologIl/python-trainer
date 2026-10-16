from __future__ import annotations

import unittest

from learning_app.domain import TaskDraft, TaskFormat
from learning_app.training_profiles import (
    build_task_plan,
    select_tasks_for_plan,
    task_plan_errors,
)


def draft(task_format: TaskFormat, index: int) -> TaskDraft:
    values = {
        "format": task_format,
        "difficulty": 1,
        "prompt": f"Задание {index}",
        "knowledge_client_ids": ["k1"],
    }
    if task_format in {TaskFormat.DEBUG, TaskFormat.OUTPUT_PREDICTION}:
        values.update(stimulus="print(1)", answer_guidance="Критерии")
    elif task_format == TaskFormat.WRITE_CODE:
        values["answer_guidance"] = "Критерии"
    else:
        values.update(options=["a", "b"], correct_answer="a")
    return TaskDraft(**values)


class TrainingProfileTests(unittest.TestCase):
    def test_python_profile_keeps_10_10_20_for_regular_session(self) -> None:
        plan = build_task_plan("python_practice", 40, ["skill"])

        self.assertEqual(
            plan.format_counts,
            {"debug": 10, "output_prediction": 10, "write_code": 20},
        )

    def test_recovery_session_scales_profile_to_16_tasks(self) -> None:
        plan = build_task_plan("python_practice", 16, ["skill"])

        self.assertEqual(
            plan.format_counts,
            {"debug": 4, "output_prediction": 4, "write_code": 8},
        )

    def test_only_wrong_distribution_slots_need_replacement(self) -> None:
        plan = build_task_plan("python_practice", 4, ["skill"])
        tasks = [
            draft(TaskFormat.DEBUG, 0),
            draft(TaskFormat.DEBUG, 1),
            draft(TaskFormat.OUTPUT_PREDICTION, 2),
            draft(TaskFormat.WRITE_CODE, 3),
        ]

        accepted, missing = select_tasks_for_plan(tasks, plan)

        self.assertEqual(len(accepted), 3)
        self.assertEqual(missing.task_count, 1)
        self.assertEqual(missing.format_counts, {"write_code": 1})

    def test_distribution_validation_reports_mismatch(self) -> None:
        plan = build_task_plan("python_practice", 4, ["skill"])
        tasks = [draft(TaskFormat.WRITE_CODE, index) for index in range(4)]

        self.assertTrue(task_plan_errors(tasks, plan))


if __name__ == "__main__":
    unittest.main()
