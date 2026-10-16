from __future__ import annotations

import unittest

from learning_app.ai.prompts import build_grading_prompt, build_task_generation_prompt


class GradingPromptTests(unittest.TestCase):
    def test_text_answer_is_rendered_without_json_quotes(self) -> None:
        system, user = build_grading_prompt(
            task={"format": "output_prediction"},
            user_answer="2",
            knowledge_context=[],
        )

        self.assertIn("пользователь ввёл кавычки", system)
        self.assertIn(
            "BEGIN_EXACT_USER_ANSWER\n2\nEND_EXACT_USER_ANSWER",
            user,
        )
        self.assertNotIn('\n"2"\n', user)

    def test_structured_answer_remains_json(self) -> None:
        _, user = build_grading_prompt(
            task={"format": "matching"},
            user_answer={"a": "b"},
            knowledge_context=[],
        )

        self.assertIn("Тип ввода: структурированное значение JSON", user)
        self.assertIn('"a": "b"', user)


class TaskGenerationPromptTests(unittest.TestCase):
    def test_recent_task_complaints_are_included_as_defects_to_avoid(self) -> None:
        system, user = build_task_generation_prompt(
            module_title="Функции",
            module_scope="Списки и функции",
            materials=[],
            knowledge_profiles=[],
            recent_history=[],
            session_kind="regular",
            task_count=10,
            task_feedback=[
                {
                    "task_format": "matching",
                    "task_prompt": "Сопоставь приём с назначением функции.",
                    "issue_type": "ошибка в условии",
                    "comment": "Не показаны элементы для сопоставления.",
                }
            ],
        )

        self.assertIn("не повторяй такой же дефект", system)
        self.assertIn("<past_task_feedback>", user)
        self.assertIn("Сопоставь приём с назначением функции.", user)
        self.assertIn("Не показаны элементы для сопоставления.", user)


if __name__ == "__main__":
    unittest.main()
