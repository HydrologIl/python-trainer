from __future__ import annotations

from typing import Any

from google import genai
from google.genai import types

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


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.5-pro") -> None:
        if not api_key:
            raise ValueError("Не задан GEMINI_API_KEY.")
        self.model = model
        self._client = genai.Client(api_key=api_key)

    def _parse(self, schema: type[Any], system_text: str, user_text: str) -> Any:
        response = call_with_transient_retry(
            lambda: self._client.models.generate_content(
                model=self.model,
                contents=user_text,
                config=types.GenerateContentConfig(
                    system_instruction=system_text,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
        )
        return schema.model_validate_json(response.text)

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
    ) -> TaskBatch:
        system_text, user_text = build_task_generation_prompt(
            module_title,
            module_scope,
            materials,
            knowledge_profiles,
            recent_history,
            session_kind,
            task_count,
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
