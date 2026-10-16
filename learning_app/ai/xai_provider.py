from __future__ import annotations

from typing import Any

from learning_app.ai.base import AIProvider
from learning_app.ai.prompts import (
    build_grading_prompt,
    build_material_analysis_prompt,
    build_task_generation_prompt,
)
from learning_app.ai.retry import call_with_transient_retry
from learning_app.domain import (
    GradingResult,
    KnowledgeProfile,
    MaterialAnalysis,
    TaskBatch,
)


class XAIProvider(AIProvider):
    name = "xai"

    def __init__(self, api_key: str, model: str = "grok-4.7") -> None:
        if not api_key:
            raise ValueError("Не задан XAI_API_KEY.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Установи пакет openai для работы с Grok API.") from exc
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")

    def _parse(self, schema: type[Any], system_text: str, user_text: str) -> Any:
        completion = call_with_transient_retry(
            lambda: self._client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ],
                response_format=schema,
            )
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("Grok не вернул структурированный ответ.")
        return parsed

    def analyze_material(
        self,
        module_title: str,
        module_scope: str,
        materials: list[dict[str, str]],
    ) -> MaterialAnalysis:
        system_text, user_text = build_material_analysis_prompt(
            module_title, module_scope, materials
        )
        return self._parse(MaterialAnalysis, system_text, user_text)

    def generate_tasks(
        self,
        module_title: str,
        module_scope: str,
        materials: list[dict[str, str]],
        knowledge_profiles: list[KnowledgeProfile],
        recent_history: list[dict[str, Any]],
        session_kind: str,
        task_count: int,
        avoid_tasks: list[dict[str, Any]] | None = None,
    ) -> TaskBatch:
        system_text, user_text = build_task_generation_prompt(
            module_title,
            module_scope,
            materials,
            knowledge_profiles,
            recent_history,
            session_kind,
            task_count,
            avoid_tasks,
        )
        return self._parse(TaskBatch, system_text, user_text)

    def grade_answer(
        self,
        task: dict[str, Any],
        user_answer: Any,
        knowledge_context: list[dict[str, str]],
    ) -> GradingResult:
        system_text, user_text = build_grading_prompt(
            task, user_answer, knowledge_context
        )
        return self._parse(GradingResult, system_text, user_text)
