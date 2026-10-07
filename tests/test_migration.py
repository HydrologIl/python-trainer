from __future__ import annotations

import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from learning_app.legacy_migration import LegacyMigrator, LegacySnapshot
from learning_app.repository import (
    Attempt,
    Course,
    LearningRepository,
    Material,
    Module,
    ReviewSession,
    Task,
)


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.repository = LearningRepository(engine=engine)
        self.repository.create_schema()
        self.migrator = LegacyMigrator(self.repository)
        self.snapshot = LegacySnapshot(
            topics=[
                {
                    "topic_id": "python_functions",
                    "stage": "Этап 0",
                    "block": 6,
                    "global_order": 6,
                    "title": "Функции",
                    "description": "Параметры и return",
                    "learned_date": "2026-10-01",
                    "status": "learned",
                    "required_core": "def, return",
                }
            ],
            sessions=[
                {
                    "session_id": "legacy_session_1",
                    "topic_id": "python_functions",
                    "repetition_day": 1,
                    "scheduled_date": "2026-10-02",
                    "started_at": "2026-10-02T10:00:00",
                    "completed_at": "2026-10-02T11:00:00",
                    "status": "completed",
                }
            ],
            tasks=[
                {
                    "task_id": "legacy_task_1",
                    "session_id": "legacy_session_1",
                    "topic_id": "python_functions",
                    "task_type": "write_code",
                    "difficulty": "начальный",
                    "task_text": "Напишите функцию.",
                    "code": "",
                    "order": 1,
                    "status": "correct",
                    "created_at": "2026-10-02T10:00:00",
                }
            ],
            answers=[
                {
                    "answer_id": "legacy_answer_1",
                    "task_id": "legacy_task_1",
                    "user_answer": "def f(): return 1",
                    "gemini_feedback": "Верно",
                    "verdict": "correct",
                    "created_at": "2026-10-02T10:10:00",
                }
            ],
            materials=[
                {
                    "material_id": "legacy_material_1",
                    "topic_id": "python_functions",
                    "title": "Конспект",
                    "material_text": "return возвращает значение",
                    "status": "active",
                }
            ],
        )

    def _counts(self) -> tuple[int, ...]:
        with self.repository.transaction() as db:
            return tuple(
                int(db.scalar(select(func.count()).select_from(model)) or 0)
                for model in (Course, Module, Material, ReviewSession, Task, Attempt)
            )

    def test_migration_preserves_history_and_is_repeatable(self) -> None:
        report = self.migrator.inspect(self.snapshot)
        self.assertEqual(report.unresolved_references, [])
        self.assertEqual(report.tasks, 1)

        self.migrator.migrate(self.snapshot)
        first_counts = self._counts()
        self.migrator.migrate(self.snapshot)
        self.assertEqual(self._counts(), first_counts)
        self.assertEqual(first_counts, (1, 1, 1, 1, 1, 1))

        module = self.repository.list_modules(self.repository.list_courses()[0].id)[0]
        attempts = self.repository.get_learning_attempts(module.id)
        self.assertEqual(attempts[0]["verdict"], "correct")
        self.assertEqual(len(attempts[0]["knowledge_ids"]), 1)


if __name__ == "__main__":
    unittest.main()
