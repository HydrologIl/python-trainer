from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from learning_app.ai.xai_provider import XAIProvider
from learning_app.domain import GradingResult, Verdict


class XAIProviderTests(unittest.TestCase):
    def setUp(self):
        parsed = GradingResult(verdict=Verdict.CORRECT, feedback="Верно")
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))]
        )
        self.parse = Mock(return_value=completion)
        self.provider = XAIProvider.__new__(XAIProvider)
        self.provider.model = "grok-4.7"
        self.provider._client = SimpleNamespace(
            beta=SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(parse=self.parse)
                )
            )
        )

    @patch(
        "learning_app.ai.xai_provider.call_with_transient_retry",
        side_effect=lambda callback: callback(),
    )
    def test_grading_uses_low_reasoning(self, _retry):
        result = self.provider.grade_answer(
            task={"prompt": "Напиши функцию", "answer_guidance": "Проверить результат"},
            user_answer="def solution(): return 1",
            knowledge_context=[],
        )

        self.assertEqual(result.verdict, Verdict.CORRECT)
        self.assertEqual(self.parse.call_args.kwargs["reasoning_effort"], "low")

    @patch(
        "learning_app.ai.xai_provider.call_with_transient_retry",
        side_effect=lambda callback: callback(),
    )
    def test_default_parse_does_not_override_reasoning(self, _retry):
        self.provider._parse(GradingResult, "system", "user")

        self.assertNotIn("reasoning_effort", self.parse.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
