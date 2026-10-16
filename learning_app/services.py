from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from learning_app.ai.base import AIProvider
from learning_app.domain import GradingResult, KnowledgeKind, KnowledgeProfile, TaskDraft
from learning_app.grading import grade_locally
from learning_app.mastery import calculate_mastery, generation_weight
from learning_app.repository import LearningRepository, ReviewSession, Task
from learning_app.scheduling import recovery_task_count
from learning_app.validation import duplicate_task_indexes, validate_task_batch


class LearningService:
    def __init__(
        self,
        repository: LearningRepository,
        ai_provider: AIProvider,
        timezone_name: str = "",
    ):
        self.repository = repository
        self.ai_provider = ai_provider
        self.timezone_name = timezone_name

    def analyze_module(self, module_id: str):
        module = self.repository.get_module(module_id)
        if module is None:
            raise ValueError("Модуль не найден.")
        materials = self.repository.list_materials(module_id)
        if not materials:
            raise ValueError("Добавь хотя бы один конспект перед анализом модуля.")

        material_rows = [
            {"title": material.title, "content": material.content}
            for material in materials
        ]
        analysis = self.ai_provider.analyze_material(
            module.title,
            module.scope_text or module.description,
            material_rows,
        )
        self.repository.upsert_knowledge_items(module_id, analysis.items)
        return analysis

    def build_knowledge_profiles(self, module_id: str) -> list[KnowledgeProfile]:
        items = self.repository.list_knowledge_items(module_id)
        mastery = calculate_mastery(self.repository.get_learning_attempts(module_id))
        profiles: list[KnowledgeProfile] = []
        for item in items:
            summary = mastery.get(item.id)
            profiles.append(
                KnowledgeProfile(
                    knowledge_id=item.client_key,
                    title=item.title,
                    kind=KnowledgeKind(item.kind),
                    mastery=summary.score if summary else 0.5,
                    attempts=summary.attempts if summary else 0,
                    recent_errors=list(summary.recent_errors) if summary else [],
                )
            )
        return sorted(
            profiles,
            key=lambda profile: generation_weight(profile.mastery, profile.attempts),
            reverse=True,
        )

    def generate_assignment(self, assignment_id: str) -> ReviewSession:
        assignment = self.repository.get_assignment(assignment_id)
        if assignment is None:
            raise ValueError("Назначенное повторение не найдено.")
        existing = self.repository.get_session_for_assignment(assignment_id)
        if existing:
            return existing

        module = self.repository.get_module(assignment.module_id)
        if module is None:
            raise ValueError("Модуль не найден.")
        materials = self.repository.list_materials(module.id)
        knowledge = self.repository.list_knowledge_items(module.id)
        if not knowledge:
            raise ValueError("Сначала проанализируй конспект и создай карту знаний модуля.")

        profiles = self.build_knowledge_profiles(module.id)
        material_rows = [
            {"title": material.title, "content": material.content}
            for material in materials
        ]
        recent_history = self.repository.get_recent_history(module.id)
        task_feedback = self.repository.get_recent_task_feedback(module.id)
        try:
            batch = self.ai_provider.generate_tasks(
                module_title=module.title,
                module_scope=module.scope_text or module.description,
                materials=material_rows,
                knowledge_profiles=profiles,
                recent_history=recent_history,
                session_kind=assignment.kind,
                task_count=assignment.task_count,
                task_feedback=task_feedback,
            )
            repaired_tasks = self._replace_duplicate_tasks(
                tasks=list(batch.tasks),
                module_title=module.title,
                module_scope=module.scope_text or module.description,
                materials=material_rows,
                knowledge_profiles=profiles,
                recent_history=recent_history,
                session_kind=assignment.kind,
                task_feedback=task_feedback,
            )
            tasks = validate_task_batch(
                repaired_tasks,
                expected_count=assignment.task_count,
                allowed_knowledge_ids={item.client_key for item in knowledge},
            )
            return self.repository.create_session_with_tasks(
                assignment_id=assignment.id,
                tasks=tasks,
                knowledge_by_client_key={item.client_key: item.id for item in knowledge},
                provider=self.ai_provider.name,
                model=self.ai_provider.model,
            )
        except Exception as exc:
            self.repository.record_generation_failure(
                module_id=module.id,
                assignment_id=assignment.id,
                provider=self.ai_provider.name,
                error_message=str(exc),
            )
            raise

    def _replace_duplicate_tasks(
        self,
        *,
        tasks: list[TaskDraft],
        module_title: str,
        module_scope: str,
        materials: list[dict[str, str]],
        knowledge_profiles: list[KnowledgeProfile],
        recent_history: list[dict[str, Any]],
        session_kind: str,
        task_feedback: list[dict[str, Any]],
        max_repair_rounds: int = 3,
    ) -> list[TaskDraft]:
        repaired = list(tasks)
        for _ in range(max_repair_rounds):
            duplicate_indexes = duplicate_task_indexes(repaired)
            if not duplicate_indexes:
                return repaired

            duplicate_set = set(duplicate_indexes)
            accepted = [
                task for index, task in enumerate(repaired) if index not in duplicate_set
            ]
            avoid_tasks = [
                {
                    "prompt": task.prompt,
                    "stimulus": task.stimulus,
                    "options": task.options,
                }
                for task in accepted
            ]
            replacements = self.ai_provider.generate_tasks(
                module_title=module_title,
                module_scope=module_scope,
                materials=materials,
                knowledge_profiles=knowledge_profiles,
                recent_history=recent_history,
                session_kind=session_kind,
                task_count=len(duplicate_indexes),
                avoid_tasks=avoid_tasks,
                task_feedback=task_feedback,
            ).tasks
            if len(replacements) != len(duplicate_indexes):
                raise ValueError(
                    "Не удалось заменить дубли: AI вернул "
                    f"{len(replacements)} заданий вместо {len(duplicate_indexes)}."
                )
            for index, replacement in zip(duplicate_indexes, replacements):
                repaired[index] = replacement

        return repaired

    def grade_task(self, task_id: str, user_answer: Any) -> GradingResult:
        task = self.repository.get_task(task_id)
        if task is None:
            raise ValueError("Задание не найдено.")

        result = grade_locally(task.format, task.correct_answer, user_answer)
        if result is None:
            knowledge_ids = self.repository.task_knowledge_ids(task.id)
            knowledge = self.repository.get_knowledge_items_by_ids(knowledge_ids)
            result = self.ai_provider.grade_answer(
                task=self._task_context(task),
                user_answer=user_answer,
                knowledge_context=[
                    {
                        "title": item.title,
                        "kind": item.kind,
                        "description": item.description,
                        "source_excerpt": item.source_excerpt,
                    }
                    for item in knowledge
                ],
            )

        self.repository.add_attempt(
            task_id=task.id,
            user_answer=user_answer,
            verdict=result.verdict.value,
            feedback=result.feedback,
            error_type=result.error_type,
            error_summary=result.error_summary,
        )

        if result.verdict.value != "correct":
            self._schedule_recovery(task.module_id)
        self.repository.complete_session_if_ready(task.session_id)
        return result

    def _schedule_recovery(self, module_id: str) -> None:
        mastery = calculate_mastery(self.repository.get_learning_attempts(module_id))
        weak_items = [summary for summary in mastery.values() if summary.score < 0.65]
        reason_parts = [
            error
            for summary in weak_items
            for error in summary.recent_errors[:2]
        ]
        reason = ", ".join(dict.fromkeys(reason_parts)) or "ошибка в последней тренировке"
        self.repository.ensure_recovery_assignment(
            module_id=module_id,
            error_date=self._today(),
            task_count=recovery_task_count(len(weak_items)),
            reason=reason,
        )

    def _today(self) -> date:
        if not self.timezone_name:
            return date.today()
        try:
            return datetime.now(ZoneInfo(self.timezone_name)).date()
        except Exception:
            return date.today()

    @staticmethod
    def _task_context(task: Task) -> dict[str, Any]:
        return {
            "format": task.format,
            "difficulty": task.difficulty,
            "prompt": task.prompt,
            "stimulus": task.stimulus,
            "answer_guidance": task.answer_guidance,
        }
