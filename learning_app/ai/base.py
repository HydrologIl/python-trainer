from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from learning_app.domain import (
    GradingResult,
    KnowledgeProfile,
    MaterialAnalysis,
    TaskBatch,
)


class AIProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def analyze_material(
        self,
        module_title: str,
        module_scope: str,
        materials: list[dict[str, str]],
    ) -> MaterialAnalysis:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def grade_answer(
        self,
        task: dict[str, Any],
        user_answer: Any,
        knowledge_context: list[dict[str, str]],
    ) -> GradingResult:
        raise NotImplementedError
