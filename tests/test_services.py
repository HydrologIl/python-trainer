from __future__ import annotations

import unittest
from datetime import date, timedelta

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
    ):
        return TaskBatch(
            tasks=[
                TaskDraft(
                    format=TaskFormat.SINGLE_CHOICE,
                    difficulty=min(5, 1 + index // 8),
                    prompt=f"Какой тест проверяет отсутствие null? Вариант {index}",
                    options=["not_null", "unique"],
                    correct_answer="not_null",
                    knowledge_client_ids=["dbt_tests"],
                )
                for index in range(task_count)
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
    ):
        self.requested_counts.append(task_count)
        self.avoid_task_counts.append(len(avoid_tasks or []))
        if len(self.requested_counts) == 1:
            tasks = [
                TaskDraft(
                    format=TaskFormat.SINGLE_CHOICE,
                    difficulty=min(5, 1 + index // 8),
                    prompt=f"Задание {index}",
                    options=["not_null", "unique"],
                    correct_answer="not_null",
                    knowledge_client_ids=["dbt_tests"],
                )
                for index in range(task_count)
            ]
            tasks[-1] = tasks[0].model_copy(deep=True)
            return TaskBatch(tasks=tasks)

        return TaskBatch(
            tasks=[
                TaskDraft(
                    format=TaskFormat.SINGLE_CHOICE,
                    difficulty=5,
                    prompt=f"Новое задание {index}",
                    options=["not_null", "unique"],
                    correct_answer="not_null",
                    knowledge_client_ids=["dbt_tests"],
                )
                for index in range(task_count)
            ]
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

        result = self.service.grade_task(tasks[0].id, "unique")
        self.assertEqual(result.verdict.value, "incorrect")
        tomorrow = date.today() + timedelta(days=1)
        recovery = [
            item
            for item in self.repository.list_due_assignments(tomorrow)
            if item.kind == "recovery"
        ]
        self.assertEqual(len(recovery), 1)
        self.assertEqual(recovery[0].task_count, 15)

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


if __name__ == "__main__":
    unittest.main()
