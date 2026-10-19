from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from learning_app.ai.base import AIProvider
from learning_app.domain import (
    GradingResult,
    KnowledgeItemDraft,
    KnowledgeKind,
    MaterialAnalysis,
    TaskBatch,
    TaskDraft,
    TaskFormat,
    Verdict,
)
from learning_app.repository import LearningRepository
from learning_app.services import LearningService


class FakeProvider(AIProvider):
    name = "fake"
    model = "fake-1"

    def analyze_material(self, module_title, module_scope, materials):
        return MaterialAnalysis(
            summary="Краткое описание",
            items=[
                KnowledgeItemDraft(
                    client_id="dbt_tests",
                    kind=KnowledgeKind.THEORY,
                    title="Встроенные тесты dbt",
                    description="Назначение unique и not_null",
                    source_excerpt="встроенные тесты unique и not_null",
                )
            ],
        )

    def generate_tasks(
        self,
        module_title,
        module_scope,
        materials,
        knowledge_profiles,
        recent_history,
        session_kind,
        task_count,
        avoid_tasks=None,
        task_feedback=None,
        task_plan=None,
    ):
        formats = []
        if task_plan and task_plan.get("format_counts"):
            for task_format, count in task_plan["format_counts"].items():
                formats.extend([TaskFormat(task_format)] * count)
        elif task_plan and task_plan.get("group_counts"):
            representatives = {
                "theory": TaskFormat.SINGLE_CHOICE,
                "analysis": TaskFormat.OUTPUT_PREDICTION,
                "creation": TaskFormat.WRITE_CODE,
            }
            for group, count in task_plan["group_counts"].items():
                formats.extend([representatives[group]] * count)
        else:
            formats = [TaskFormat.SINGLE_CHOICE] * task_count
        prefix = "Новое задание" if avoid_tasks else "Задание"

        def make_task(index, task_format):
            common = {
                "format": task_format,
                "difficulty": min(5, 1 + index // 8),
                "prompt": f"{prefix} {index}",
                "knowledge_client_ids": ["dbt_tests"],
            }
            if task_format == TaskFormat.SINGLE_CHOICE:
                common.update(
                    options=["not_null", "unique"],
                    correct_answer="not_null",
                )
            elif task_format in {TaskFormat.DEBUG, TaskFormat.OUTPUT_PREDICTION}:
                common.update(
                    stimulus="print(1)",
                    answer_guidance="Проверить объяснение результата.",
                )
            else:
                common["answer_guidance"] = "Проверить корректность решения."
            return TaskDraft(**common)

        return TaskBatch(
            tasks=[
                make_task(index, task_format)
                for index, task_format in enumerate(formats)
            ]
        )

    def grade_answer(self, task, user_answer, knowledge_context):
        return GradingResult(verdict=Verdict.CORRECT, feedback="Верно")


class DuplicateRepairProvider(FakeProvider):
    def __init__(self):
        self.requested_counts = []
        self.avoid_task_counts = []

    def generate_tasks(
        self,
        module_title,
        module_scope,
        materials,
        knowledge_profiles,
        recent_history,
        session_kind,
        task_count,
        avoid_tasks=None,
        task_feedback=None,
        task_plan=None,
    ):
        self.requested_counts.append(task_count)
        self.avoid_task_counts.append(len(avoid_tasks or []))
        batch = super().generate_tasks(
            module_title,
            module_scope,
            materials,
            knowledge_profiles,
            recent_history,
            session_kind,
            task_count,
            avoid_tasks,
            task_feedback,
            task_plan,
        )
        if len(self.requested_counts) == 1:
            first_by_format = {}
            for index, task in enumerate(batch.tasks):
                previous = first_by_format.get(task.format)
                if previous is not None:
                    batch.tasks[index] = batch.tasks[previous].model_copy(deep=True)
                    break
                first_by_format[task.format] = index
        return batch


class DistributionRepairProvider(FakeProvider):
    def __init__(self):
        self.requested_counts = []

    def generate_tasks(
        self,
        module_title,
        module_scope,
        materials,
        knowledge_profiles,
        recent_history,
        session_kind,
        task_count,
        avoid_tasks=None,
        task_feedback=None,
        task_plan=None,
    ):
        self.requested_counts.append(task_count)
        if len(self.requested_counts) == 1:
            return TaskBatch(
                tasks=[
                    TaskDraft(
                        format=TaskFormat.SINGLE_CHOICE,
                        difficulty=min(5, 1 + index // 8),
                        prompt=f"Только теория {index}",
                        options=["not_null", "unique"],
                        correct_answer="not_null",
                        knowledge_client_ids=["dbt_tests"],
                    )
                    for index in range(task_count)
                ]
            )
        return super().generate_tasks(
            module_title,
            module_scope,
            materials,
            knowledge_profiles,
            recent_history,
            session_kind,
            task_count,
            avoid_tasks,
            task_feedback,
            task_plan,
        )


class LearningServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.repository = LearningRepository(engine=engine)
        self.repository.create_schema()
        self.service = LearningService(self.repository, FakeProvider())
        course = self.repository.create_course("dbt")
        self.module = self.repository.add_module(course.id, "Тесты dbt")
        self.repository.add_material(
            self.module.id,
            "Конспект",
            "В dbt есть встроенные тесты unique и not_null.",
        )

    def test_vertical_learning_flow_and_recovery(self) -> None:
        analysis = self.service.analyze_module(self.module.id)
        self.assertEqual(len(analysis.items), 1)

        learned = date.today() - timedelta(days=1)
        self.repository.mark_module_studied(self.module.id, learned)
        assignment = [
            item
            for item in self.repository.list_due_assignments(date.today())
            if item.repetition_day == 1
        ][0]
        review = self.service.generate_assignment(assignment.id)
        tasks = self.repository.list_tasks(review.id)
        self.assertEqual(len(tasks), 40)
        self.assertEqual(tasks[0].difficulty, 1)
        self.assertEqual(tasks[-1].difficulty, 5)

        locally_graded = next(
            task for task in tasks if task.format == TaskFormat.SINGLE_CHOICE.value
        )
        result = self.service.grade_task(locally_graded.id, "unique")
        self.assertEqual(result.verdict.value, "incorrect")
        tomorrow = date.today() + timedelta(days=1)
        recovery = [
            item
            for item in self.repository.list_due_assignments(tomorrow)
            if item.kind == "recovery"
        ]
        self.assertEqual(len(recovery), 1)
        self.assertEqual(recovery[0].task_count, 15)

    def test_error_in_recovery_does_not_schedule_another_recovery(self) -> None:
        self.service.analyze_module(self.module.id)
        today = date.today()
        self.repository.mark_module_studied(self.module.id, today - timedelta(days=1))
        regular_assignment = next(
            item
            for item in self.repository.list_due_assignments(today)
            if item.repetition_day == 1
        )
        regular_session = self.service.generate_assignment(regular_assignment.id)
        regular_task = next(
            task
            for task in self.repository.list_tasks(regular_session.id)
            if task.format == TaskFormat.SINGLE_CHOICE.value
        )
        self.service.grade_task(regular_task.id, "unique")

        tomorrow = today + timedelta(days=1)
        recovery_assignment = next(
            item
            for item in self.repository.list_due_assignments(tomorrow)
            if item.kind == "recovery"
        )
        recovery_session = self.service.generate_assignment(recovery_assignment.id)
        recovery_task = next(
            task
            for task in self.repository.list_tasks(recovery_session.id)
            if task.format == TaskFormat.SINGLE_CHOICE.value
        )
        with patch.object(self.service, "_today", return_value=tomorrow):
            result = self.service.grade_task(recovery_task.id, "unique")

        self.assertEqual(result.verdict.value, "incorrect")
        recoveries = [
            item
            for item in self.repository.list_due_assignments(tomorrow + timedelta(days=1))
            if item.kind == "recovery"
        ]
        self.assertEqual(len(recoveries), 1)
        self.assertEqual(recoveries[0].scheduled_date, tomorrow)

    def test_only_complete_duplicates_are_regenerated(self) -> None:
        provider = DuplicateRepairProvider()
        service = LearningService(self.repository, provider)
        service.analyze_module(self.module.id)
        self.repository.mark_module_studied(self.module.id, date.today() - timedelta(days=1))
        assignment = [
            item
            for item in self.repository.list_due_assignments(date.today())
            if item.repetition_day == 1
        ][0]

        review = service.generate_assignment(assignment.id)

        self.assertEqual(len(self.repository.list_tasks(review.id)), 40)
        self.assertEqual(provider.requested_counts, [40, 1])
        self.assertEqual(provider.avoid_task_counts, [0, 39])

    def test_only_missing_profile_groups_are_regenerated(self) -> None:
        provider = DistributionRepairProvider()
        service = LearningService(self.repository, provider)
        service.analyze_module(self.module.id)
        self.repository.mark_module_studied(self.module.id, date.today() - timedelta(days=1))
        assignment = [
            item
            for item in self.repository.list_due_assignments(date.today())
            if item.repetition_day == 1
        ][0]

        review = service.generate_assignment(assignment.id)
        tasks = self.repository.list_tasks(review.id)

        self.assertEqual(provider.requested_counts, [40, 16])
        self.assertEqual(
            sum(task.format == TaskFormat.SINGLE_CHOICE.value for task in tasks),
            24,
        )
        self.assertEqual(
            sum(task.format == TaskFormat.OUTPUT_PREDICTION.value for task in tasks),
            10,
        )
        self.assertEqual(
            sum(task.format == TaskFormat.WRITE_CODE.value for task in tasks),
            6,
        )


if __name__ == "__main__":
    unittest.main()
