from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from learning_app.ai.retry import call_with_transient_retry
from learning_app.domain import TaskDraft, TaskFormat
from learning_app.grading import grade_locally
from learning_app.mastery import calculate_mastery, generation_weight, needs_recovery
from learning_app.scheduling import (
    due_regular_slots,
    recovery_slot,
    recovery_task_count,
    regular_review_slots,
)
from learning_app.validation import validate_task_batch


class SchedulingTests(unittest.TestCase):
    def test_regular_review_dates(self) -> None:
        slots = regular_review_slots(date(2026, 10, 1))
        self.assertEqual(
            [slot.scheduled_date.isoformat() for slot in slots],
            ["2026-10-02", "2026-10-04", "2026-10-08", "2026-10-15", "2026-10-31"],
        )

    def test_due_reviews_keep_overdue_items(self) -> None:
        completed = {"regular:1:2026-10-02"}
        slots = due_regular_slots(date(2026, 10, 1), date(2026, 10, 8), completed)
        self.assertEqual([slot.repetition_day for slot in slots], [3, 7])

    def test_recovery_is_next_day_and_short(self) -> None:
        self.assertEqual(recovery_slot(date(2026, 10, 7)).scheduled_date, date(2026, 10, 8))
        self.assertEqual(recovery_task_count(2), 15)
        self.assertEqual(recovery_task_count(5), 18)
        self.assertEqual(recovery_task_count(9), 20)


class MasteryTests(unittest.TestCase):
    def test_recent_attempts_have_more_weight(self) -> None:
        summaries = calculate_mastery(
            [
                {
                    "knowledge_ids": ["k1"],
                    "verdict": "incorrect",
                    "error_type": "missing_return",
                    "created_at": "2026-10-01T10:00:00",
                },
                {
                    "knowledge_ids": ["k1"],
                    "verdict": "correct",
                    "created_at": "2026-10-02T10:00:00",
                },
            ]
        )
        self.assertGreater(summaries["k1"].score, 0.5)
        self.assertIn("missing_return", summaries["k1"].recent_errors)

    def test_weak_or_unknown_items_get_more_generation_weight(self) -> None:
        self.assertGreater(generation_weight(0.2, 4), generation_weight(0.9, 4))
        self.assertGreater(generation_weight(0.5, 0), generation_weight(0.5, 3))

    def test_recovery_threshold(self) -> None:
        self.assertTrue(needs_recovery(["incorrect", "incorrect"]))
        self.assertTrue(
            needs_recovery(["partially_correct", "incorrect", "partially_correct"])
        )
        self.assertFalse(needs_recovery(["correct", "partially_correct"]))


class GradingTests(unittest.TestCase):
    def test_multiple_choice_ignores_order(self) -> None:
        result = grade_locally("multiple_choice", ["A", "C"], ["c", "a"])
        self.assertIsNotNone(result)
        self.assertEqual(result.verdict.value, "correct")

    def test_ordering_respects_order(self) -> None:
        result = grade_locally("ordering", ["one", "two"], ["two", "one"])
        self.assertIsNotNone(result)
        self.assertEqual(result.verdict.value, "incorrect")

    def test_practical_requires_ai(self) -> None:
        self.assertIsNone(grade_locally("write_code", None, "print('ok')"))


class ValidationTests(unittest.TestCase):
    def test_valid_batch_is_sorted_by_difficulty(self) -> None:
        tasks = [
            TaskDraft(
                format=TaskFormat.TRUE_FALSE,
                difficulty=3,
                prompt="Третья?",
                correct_answer=True,
                knowledge_client_ids=["k1"],
            ),
            TaskDraft(
                format=TaskFormat.SINGLE_CHOICE,
                difficulty=1,
                prompt="Первая?",
                options=["да", "нет"],
                correct_answer="да",
                knowledge_client_ids=["k1"],
            ),
        ]
        result = validate_task_batch(tasks, expected_count=2, allowed_knowledge_ids={"k1"})
        self.assertEqual([task.difficulty for task in result], [1, 3])

    def test_unknown_knowledge_item_is_rejected(self) -> None:
        task = TaskDraft(
            format=TaskFormat.TRUE_FALSE,
            difficulty=1,
            prompt="Проверка?",
            correct_answer=True,
            knowledge_client_ids=["missing"],
        )
        with self.assertRaisesRegex(ValueError, "неизвест"):
            validate_task_batch([task], expected_count=1, allowed_knowledge_ids={"k1"})


class RetryTests(unittest.TestCase):
    @patch("learning_app.ai.retry.time.sleep")
    def test_transient_failures_are_retried(self, sleep) -> None:
        calls = 0

        def operation():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError("503 temporarily unavailable")
            return "ok"

        self.assertEqual(
            call_with_transient_retry(operation, initial_delay_seconds=0.01),
            "ok",
        )
        self.assertEqual(calls, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch("learning_app.ai.retry.time.sleep")
    def test_non_transient_failures_are_not_retried(self, sleep) -> None:
        def operation():
            raise ValueError("invalid schema")

        with self.assertRaisesRegex(ValueError, "invalid schema"):
            call_with_transient_retry(operation)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
