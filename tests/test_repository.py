from __future__ import annotations

import unittest
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from learning_app.domain import KnowledgeItemDraft, KnowledgeKind, TaskDraft, TaskFormat
from learning_app.repository import LearningRepository


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.repository = LearningRepository(engine=engine)
        self.repository.create_schema()
        self.course = self.repository.create_course("Python")
        self.module = self.repository.add_module(self.course.id, "Функции")

    def test_mark_studied_creates_five_idempotent_assignments(self) -> None:
        self.repository.mark_module_studied(self.module.id, date(2026, 10, 1))
        self.repository.mark_module_studied(self.module.id, date(2026, 10, 1))
        due = self.repository.list_due_assignments(date(2026, 11, 1))
        self.assertEqual(len(due), 5)
        self.assertTrue(all(item.task_count == 40 for item in due))

        due_with_modules = self.repository.list_due_assignments_with_modules(
            date(2026, 11, 1)
        )
        self.assertEqual(len(due_with_modules), 5)
        self.assertTrue(all(title == "Функции" for _, title in due_with_modules))

    def test_changing_learned_date_replaces_only_pending_regular_schedule(self) -> None:
        self.repository.mark_module_studied(self.module.id, date(2026, 10, 1))
        self.repository.mark_module_studied(self.module.id, date(2026, 10, 10))

        due = self.repository.list_due_assignments(date(2026, 11, 15))
        self.assertEqual(len(due), 5)
        self.assertEqual(due[0].scheduled_date, date(2026, 10, 11))
        self.assertEqual(due[-1].scheduled_date, date(2026, 11, 9))

    def test_editing_material_and_reanalysis_deactivates_stale_knowledge(self) -> None:
        material = self.repository.add_material(
            self.module.id,
            "Черновик",
            "Старый текст",
        )
        self.repository.upsert_knowledge_items(
            self.module.id,
            [
                KnowledgeItemDraft(
                    client_id="old_fact",
                    kind=KnowledgeKind.THEORY,
                    title="Старый факт",
                    description="Описание",
                )
            ],
        )

        self.repository.update_material(material.id, "Исправленный", "Новый текст")
        self.repository.upsert_knowledge_items(
            self.module.id,
            [
                KnowledgeItemDraft(
                    client_id="new_fact",
                    kind=KnowledgeKind.THEORY,
                    title="Новый факт",
                    description="Описание",
                )
            ],
        )

        saved_material = self.repository.list_materials(self.module.id)[0]
        active_items = self.repository.list_knowledge_items(self.module.id)
        self.assertEqual(saved_material.title, "Исправленный")
        self.assertEqual(saved_material.content, "Новый текст")
        self.assertEqual([item.client_key for item in active_items], ["new_fact"])

    def test_session_and_tasks_are_atomic_and_idempotent(self) -> None:
        mapping = self.repository.upsert_knowledge_items(
            self.module.id,
            [
                KnowledgeItemDraft(
                    client_id="return",
                    kind=KnowledgeKind.SKILL,
                    title="return",
                    description="Возврат значения",
                )
            ],
        )
        self.repository.mark_module_studied(self.module.id, date(2026, 10, 1))
        assignment = self.repository.list_due_assignments(date(2026, 10, 2))[0]
        assignment.task_count = 1
        with self.repository.transaction() as session:
            session.merge(assignment)

        tasks = [
            TaskDraft(
                format=TaskFormat.WRITE_CODE,
                difficulty=2,
                prompt="Напишите функцию.",
                knowledge_client_ids=["return"],
            )
        ]
        first = self.repository.create_session_with_tasks(
            assignment.id, tasks, mapping, provider="fake", model="fake-1"
        )
        second = self.repository.create_session_with_tasks(
            assignment.id, tasks, mapping, provider="fake", model="fake-1"
        )
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(self.repository.list_tasks(first.id)), 1)

    def test_skip_does_not_complete_session(self) -> None:
        mapping = self.repository.upsert_knowledge_items(
            self.module.id,
            [
                KnowledgeItemDraft(
                    client_id="k1",
                    kind=KnowledgeKind.THEORY,
                    title="Факт",
                    description="Описание",
                )
            ],
        )
        self.repository.mark_module_studied(self.module.id, date(2026, 10, 1))
        assignment = self.repository.list_due_assignments(date(2026, 10, 2))[0]
        assignment.task_count = 1
        with self.repository.transaction() as session:
            session.merge(assignment)
        task = TaskDraft(
            format=TaskFormat.TRUE_FALSE,
            difficulty=1,
            prompt="Верно?",
            correct_answer=True,
            knowledge_client_ids=["k1"],
        )
        review = self.repository.create_session_with_tasks(
            assignment.id, [task], mapping, provider="fake", model="fake"
        )
        stored = self.repository.list_tasks(review.id)[0]
        self.repository.set_task_status(stored.id, "skipped")
        self.assertFalse(self.repository.complete_session_if_ready(review.id))
        self.repository.set_task_status(stored.id, "abandoned")
        self.assertTrue(self.repository.complete_session_if_ready(review.id))

    def test_latest_attempt_preserves_the_last_answer(self) -> None:
        mapping = self.repository.upsert_knowledge_items(
            self.module.id,
            [
                KnowledgeItemDraft(
                    client_id="k1",
                    kind=KnowledgeKind.THEORY,
                    title="Факт",
                    description="Описание",
                )
            ],
        )
        self.repository.mark_module_studied(self.module.id, date(2026, 10, 1))
        assignment = self.repository.list_due_assignments(date(2026, 10, 2))[0]
        assignment.task_count = 1
        with self.repository.transaction() as session:
            session.merge(assignment)
        review = self.repository.create_session_with_tasks(
            assignment.id,
            [
                TaskDraft(
                    format=TaskFormat.TRUE_FALSE,
                    difficulty=1,
                    prompt="Верно?",
                    correct_answer=False,
                    knowledge_client_ids=["k1"],
                )
            ],
            mapping,
            provider="fake",
            model="fake",
        )
        task = self.repository.list_tasks(review.id)[0]
        self.repository.add_attempt(
            task.id,
            "Верно",
            "incorrect",
            "Ошибка",
            created_at=datetime(2026, 10, 2, 10, 0),
        )
        latest = self.repository.add_attempt(
            task.id,
            "Неверно",
            "correct",
            "Верно.",
            created_at=datetime(2026, 10, 2, 10, 1),
        )

        restored = self.repository.get_latest_attempt(task.id)

        self.assertEqual(restored.id, latest.id)
        self.assertEqual(restored.user_answer, "Неверно")

        self.repository.add_task_feedback(
            task.id,
            "ошибка в условии",
            "Не хватает данных для ответа.",
        )
        flagged = self.repository.get_task(task.id)
        self.assertEqual(flagged.status, "bad_task")
        self.assertTrue(self.repository.complete_session_if_ready(review.id))
        feedback = self.repository.get_recent_task_feedback(self.module.id)
        self.assertEqual(len(feedback), 1)
        self.assertEqual(feedback[0]["task_prompt"], "Верно?")
        self.assertEqual(feedback[0]["issue_type"], "ошибка в условии")
        self.assertEqual(feedback[0]["comment"], "Не хватает данных для ответа.")

        progress = self.repository.get_progress_overview()
        module_progress = next(row for row in progress if row.module_id == self.module.id)
        self.assertEqual(module_progress.course_title, "Python")
        self.assertEqual(module_progress.attempt_count, 2)


if __name__ == "__main__":
    unittest.main()
