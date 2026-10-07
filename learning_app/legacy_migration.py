from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select

from learning_app.repository import (
    Attempt,
    Course,
    KnowledgeItem,
    Material,
    Module,
    ReviewAssignment,
    ReviewSession,
    Task,
    TaskKnowledgeLink,
    LearningRepository,
    new_id,
    utc_now,
)
from learning_app.scheduling import regular_review_slots


@dataclass
class LegacySnapshot:
    topics: list[dict[str, Any]] = field(default_factory=list)
    sessions: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    answers: list[dict[str, Any]] = field(default_factory=list)
    materials: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MigrationReport:
    topics: int = 0
    sessions: int = 0
    tasks: int = 0
    answers: int = 0
    materials: int = 0
    unresolved_references: list[str] = field(default_factory=list)
    dry_run: bool = True


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _date(value: Any) -> Optional[date]:
    text = _text(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _datetime(value: Any) -> Optional[datetime]:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        parsed = _date(text)
        return datetime.combine(parsed, datetime.min.time()) if parsed else None


def _difficulty(value: Any) -> int:
    normalized = _text(value).casefold()
    if normalized in {"1", "начальный", "лёгкий", "легкий", "easy", "beginner"}:
        return 1
    if normalized in {"2", "ниже среднего"}:
        return 2
    if normalized in {"4", "сложный", "hard"}:
        return 4
    if normalized in {"5", "продвинутый", "advanced"}:
        return 5
    return 3


def _task_status(value: Any) -> str:
    normalized = _text(value) or "new"
    return "correct" if normalized == "answered" else normalized


def _module_scope(topic: dict[str, Any]) -> str:
    fields = [
        ("Цель", topic.get("goal")),
        ("Обязательное ядро", topic.get("required_core")),
        ("Частотные конструкции", topic.get("frequent_constructs")),
        ("Типовые ошибки", topic.get("common_mistakes")),
        ("Пока не трогать", topic.get("do_not_touch")),
        ("Критерий готовности", topic.get("readiness_criteria")),
    ]
    return "\n\n".join(f"{label}:\n{_text(value)}" for label, value in fields if _text(value))


class LegacyMigrator:
    def __init__(self, repository: LearningRepository):
        self.repository = repository

    def inspect(self, snapshot: LegacySnapshot) -> MigrationReport:
        report = MigrationReport(
            topics=len([row for row in snapshot.topics if _text(row.get("topic_id"))]),
            sessions=len([row for row in snapshot.sessions if _text(row.get("session_id"))]),
            tasks=len([row for row in snapshot.tasks if _text(row.get("task_id"))]),
            answers=len([row for row in snapshot.answers if _text(row.get("answer_id"))]),
            materials=len(snapshot.materials),
            dry_run=True,
        )
        topic_ids = {_text(row.get("topic_id")) for row in snapshot.topics}
        session_ids = {_text(row.get("session_id")) for row in snapshot.sessions}
        task_ids = {_text(row.get("task_id")) for row in snapshot.tasks}

        for row in snapshot.sessions:
            if _text(row.get("topic_id")) not in topic_ids:
                report.unresolved_references.append(
                    f"Сессия {_text(row.get('session_id'))}: неизвестная тема {_text(row.get('topic_id'))}."
                )
        for row in snapshot.tasks:
            if _text(row.get("session_id")) not in session_ids:
                report.unresolved_references.append(
                    f"Задание {_text(row.get('task_id'))}: неизвестная сессия {_text(row.get('session_id'))}."
                )
        for row in snapshot.answers:
            if _text(row.get("task_id")) not in task_ids:
                report.unresolved_references.append(
                    f"Ответ {_text(row.get('answer_id'))}: неизвестное задание {_text(row.get('task_id'))}."
                )
        return report

    def migrate(self, snapshot: LegacySnapshot) -> MigrationReport:
        report = self.inspect(snapshot)
        report.dry_run = False
        if report.unresolved_references:
            raise ValueError(
                "Миграция остановлена из-за нарушенных ссылок:\n- "
                + "\n- ".join(report.unresolved_references[:30])
            )

        with self.repository.transaction() as db:
            course = db.scalar(select(Course).where(Course.legacy_id == "legacy:python"))
            if course is None:
                course = Course(
                    id=new_id("course"),
                    title="Python",
                    description="Активный курс, перенесённый из Python Trainer.",
                    legacy_id="legacy:python",
                )
                db.add(course)
                db.flush()

            ordered_topics = sorted(
                [row for row in snapshot.topics if _text(row.get("topic_id"))],
                key=lambda row: (
                    _integer(row.get("global_order"), 10_000),
                    _text(row.get("stage")),
                    _integer(row.get("block")),
                ),
            )
            module_by_legacy: dict[str, Module] = {}
            overall_knowledge: dict[str, KnowledgeItem] = {}

            for position, row in enumerate(ordered_topics, start=1):
                legacy_id = _text(row.get("topic_id"))
                module = db.scalar(select(Module).where(Module.legacy_id == legacy_id))
                if module is None:
                    description = _text(row.get("description"))
                    stage = _text(row.get("stage_title") or row.get("stage"))
                    if stage:
                        description = f"{stage}\n\n{description}".strip()
                    module = Module(
                        id=new_id("module"),
                        course_id=course.id,
                        position=position,
                        title=_text(row.get("title")) or legacy_id,
                        description=description,
                        scope_text=_module_scope(row),
                        status=_text(row.get("status")) or "planned",
                        learned_date=_date(row.get("learned_date")),
                        legacy_id=legacy_id,
                    )
                    db.add(module)
                    db.flush()
                module_by_legacy[legacy_id] = module

                knowledge = db.scalar(
                    select(KnowledgeItem).where(
                        KnowledgeItem.module_id == module.id,
                        KnowledgeItem.client_key == "legacy_module_overall",
                    )
                )
                if knowledge is None:
                    knowledge = KnowledgeItem(
                        id=new_id("knowledge"),
                        module_id=module.id,
                        client_key="legacy_module_overall",
                        kind="skill",
                        title=f"Общее освоение: {module.title}",
                        description="Исторические задания до построения детальной карты знаний.",
                    )
                    db.add(knowledge)
                overall_knowledge[legacy_id] = knowledge

                if module.learned_date:
                    for slot in regular_review_slots(module.learned_date):
                        key = f"{module.id}:{slot.idempotency_suffix}"
                        assignment = db.scalar(
                            select(ReviewAssignment).where(
                                ReviewAssignment.idempotency_key == key
                            )
                        )
                        if assignment is None:
                            db.add(
                                ReviewAssignment(
                                    id=new_id("assignment"),
                                    module_id=module.id,
                                    kind="regular",
                                    scheduled_date=slot.scheduled_date,
                                    repetition_day=slot.repetition_day,
                                    task_count=40,
                                    idempotency_key=key,
                                )
                            )

            for row in snapshot.materials:
                topic_id = _text(row.get("topic_id"))
                module = module_by_legacy.get(topic_id)
                content = _text(row.get("material_text"))
                if module is None or not content:
                    continue
                legacy_id = _text(row.get("material_id")) or f"legacy-material:{topic_id}:{len(content)}"
                exists = db.scalar(select(Material.id).where(Material.legacy_id == legacy_id))
                if not exists:
                    db.add(
                        Material(
                            id=new_id("material"),
                            module_id=module.id,
                            title=_text(row.get("title")) or "Материал Python Trainer",
                            content=content,
                            status=_text(row.get("status")) or "active",
                            legacy_id=legacy_id,
                            created_at=_datetime(row.get("created_at")) or utc_now(),
                        )
                    )

            session_by_legacy: dict[str, ReviewSession] = {}
            for row in snapshot.sessions:
                legacy_id = _text(row.get("session_id"))
                module = module_by_legacy[_text(row.get("topic_id"))]
                review = db.scalar(
                    select(ReviewSession).where(ReviewSession.legacy_id == legacy_id)
                )
                if review is None:
                    repetition_day = _integer(row.get("repetition_day"), 0)
                    scheduled = _date(row.get("scheduled_date")) or date.today()
                    kind = "recovery" if repetition_day == -1 else "regular"
                    key = (
                        f"{module.id}:regular:{repetition_day}:{scheduled.isoformat()}"
                        if kind == "regular"
                        else f"{module.id}:legacy-recovery:{legacy_id}"
                    )
                    assignment = db.scalar(
                        select(ReviewAssignment).where(
                            ReviewAssignment.idempotency_key == key
                        )
                    )
                    if assignment is None or db.scalar(
                        select(ReviewSession.id).where(
                            ReviewSession.assignment_id == assignment.id
                        )
                    ):
                        key = f"{module.id}:legacy-session:{legacy_id}"
                        assignment = ReviewAssignment(
                            id=new_id("assignment"),
                            module_id=module.id,
                            kind=kind,
                            scheduled_date=scheduled,
                            repetition_day=None if repetition_day == -1 else repetition_day,
                            task_count=0,
                            idempotency_key=key,
                        )
                        db.add(assignment)
                        db.flush()

                    status = _text(row.get("status")) or "in_progress"
                    assignment.status = "completed" if status == "completed" else "in_progress"
                    review = ReviewSession(
                        id=new_id("session"),
                        module_id=module.id,
                        assignment_id=assignment.id,
                        kind=kind,
                        scheduled_date=scheduled,
                        repetition_day=None if repetition_day == -1 else repetition_day,
                        status=status,
                        legacy_id=legacy_id,
                        started_at=_datetime(row.get("started_at")) or utc_now(),
                        completed_at=_datetime(row.get("completed_at")),
                    )
                    db.add(review)
                session_by_legacy[legacy_id] = review

            task_by_legacy: dict[str, Task] = {}
            task_rows_by_session: dict[str, list[dict[str, Any]]] = {}
            for row in snapshot.tasks:
                task_rows_by_session.setdefault(_text(row.get("session_id")), []).append(row)

            for legacy_session_id, rows in task_rows_by_session.items():
                review = session_by_legacy[legacy_session_id]
                module_legacy_id = next(
                    key for key, value in module_by_legacy.items() if value.id == review.module_id
                )
                knowledge = overall_knowledge[module_legacy_id]
                ordered = sorted(rows, key=lambda row: _integer(row.get("order")))
                for position, row in enumerate(ordered, start=1):
                    legacy_id = _text(row.get("task_id"))
                    task = db.scalar(select(Task).where(Task.legacy_id == legacy_id))
                    if task is None:
                        task = Task(
                            id=new_id("task"),
                            session_id=review.id,
                            module_id=review.module_id,
                            position=position,
                            format=_text(row.get("task_type") or row.get("type")) or "practical_open",
                            difficulty=_difficulty(row.get("difficulty")),
                            prompt=_text(row.get("task_text") or row.get("task")),
                            stimulus=_text(row.get("code")),
                            options=[],
                            correct_answer=None,
                            answer_guidance="Оцени решение в рамках исходной темы Python Trainer.",
                            status=_task_status(row.get("status")),
                            provider_metadata={"provider": "legacy", "model": "gemini"},
                            legacy_id=legacy_id,
                            created_at=_datetime(row.get("created_at")) or utc_now(),
                        )
                        db.add(task)
                        db.add(
                            TaskKnowledgeLink(
                                task_id=task.id,
                                knowledge_item_id=knowledge.id,
                            )
                        )
                    task_by_legacy[legacy_id] = task

                assignment = db.get(ReviewAssignment, review.assignment_id)
                if assignment:
                    assignment.task_count = len(ordered)

            for row in snapshot.answers:
                legacy_id = _text(row.get("answer_id"))
                task = task_by_legacy[_text(row.get("task_id"))]
                exists = db.scalar(select(Attempt.id).where(Attempt.legacy_id == legacy_id))
                if exists:
                    continue
                verdict = _text(row.get("verdict")) or "unknown"
                db.add(
                    Attempt(
                        id=new_id("attempt"),
                        task_id=task.id,
                        session_id=task.session_id,
                        user_answer=_text(row.get("user_answer")),
                        verdict=verdict,
                        feedback=_text(row.get("gemini_feedback")),
                        legacy_id=legacy_id,
                        created_at=_datetime(row.get("created_at")) or utc_now(),
                    )
                )

        return report
