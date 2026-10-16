from __future__ import annotations

import unittest
from types import SimpleNamespace

from learning_app.streamlit_app import _next_unfinished_task_index


class SessionNavigationTests(unittest.TestCase):
    def test_excluded_task_advances_to_next_unfinished_task(self) -> None:
        tasks = [
            SimpleNamespace(status="correct"),
            SimpleNamespace(status="bad_task"),
            SimpleNamespace(status="new"),
        ]

        self.assertEqual(_next_unfinished_task_index(tasks, 1), 2)

    def test_navigation_wraps_to_an_earlier_unfinished_task(self) -> None:
        tasks = [
            SimpleNamespace(status="skipped"),
            SimpleNamespace(status="correct"),
            SimpleNamespace(status="abandoned"),
        ]

        self.assertEqual(_next_unfinished_task_index(tasks, 2), 0)


if __name__ == "__main__":
    unittest.main()
