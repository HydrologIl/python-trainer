from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterator, Optional

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from learning_app.domain import KnowledgeItemDraft, TaskDraft
from learning_app.scheduling import recovery_slot, regular_review_slots


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def utc_now() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


@dataclass(frozen=True)
class ProgressRow:
    course_id: str
    course_title: str
    module_id: Optional[str]
    module_position: Optional[int]
    module_title: Optional[str]
    module_status: Optional[str]
    attempt_count: int


@dataclass(frozen=True)
class ProfilePreference:
    profile_key: str
    config: dict[str, Any]
    source: str


class Base(DeclarativeBase):
    pass


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    legacy_id: Mapped[Optional[str]] = mapped_column(String(240), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class TrainingProfileSetting(Base):
    __tablename__ = "training_profile_settings"

    scope_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    scope_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    profile_key: Mapped[str] = mapped_column(String(48), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class Module(Base):
    __tablename__ = "modules"
    __table_args__ = (
        UniqueConstraint("course_id", "position", name="uq_module_course_position"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    scope_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    learned_date: Mapped[Optional[date]] = mapped_column(Date)
    legacy_id: Mapped[Optional[str]] = mapped_column(String(240), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    module_id: Mapped[str] = mapped_column(ForeignKey("modules.id"), index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    legacy_id: Mapped[Optional[str]] = mapped_column(String(240), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"
    __table_args__ = (
        UniqueConstraint("module_id", "client_key", name="uq_knowledge_module_client_key"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    module_id: Mapped[str] = mapped_column(ForeignKey("modules.id"), index=True)
    client_key: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_excerpt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class ReviewAssignment(Base):
    __tablename__ = "review_assignments"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    module_id: Mapped[str] = mapped_column(ForeignKey("modules.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    repetition_day: Mapped[Optional[int]] = mapped_column(Integer)
    task_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class ReviewSession(Base):
    __tablename__ = "review_sessions"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    module_id: Mapped[str] = mapped_column(ForeignKey("modules.id"), index=True)
    assignment_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("review_assignments.id"), unique=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    repetition_day: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="in_progress", nullable=False)
    legacy_id: Mapped[Optional[str]] = mapped_column(String(240), unique=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("session_id", "position", name="uq_task_session_position"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("review_sessions.id"), index=True)
    module_id: Mapped[str] = mapped_column(ForeignKey("modules.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    format: Mapped[str] = mapped_column(String(48), nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    stimulus: Mapped[str] = mapped_column(Text, default="", nullable=False)
    options: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    correct_answer: Mapped[Any] = mapped_column(JSON)
    answer_guidance: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False)
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    legacy_id: Mapped[Optional[str]] = mapped_column(String(240), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class TaskKnowledgeLink(Base):
    __tablename__ = "task_knowledge_links"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    knowledge_item_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_items.id"), primary_key=True, index=True
    )


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("review_sessions.id"), index=True)
    user_answer: Mapped[Any] = mapped_column(JSON, nullable=False)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    feedback: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_type: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    error_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    legacy_id: Mapped[Optional[str]] = mapped_column(String(240), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class TaskFeedback(Base):
    __tablename__ = "task_feedback"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    issue_type: Mapped[str] = mapped_column(String(120), nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class GenerationFailure(Base):
    __tablename__ = "generation_failures"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    assignment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("review_assignments.id"))
    module_id: Mapped[str] = mapped_column(ForeignKey("modules.id"), index=True)
    provider: Mapped[str] = mapped_column(String(48), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


def create_database_engine(database_url: Optional[str] = None) -> Engine:
    url = database_url or os.getenv("DATABASE_URL") or "sqlite:///learning_app.db"
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


class LearningRepository:
    def __init__(self, database_url: Optional[str] = None, engine: Optional[Engine] = None):
        self.engine = engine or create_database_engine(database_url)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False, future=True)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self._sessions.begin() as session:
            yield session

    def create_course(
        self,
        title: str,
        description: str = "",
        legacy_id: Optional[str] = None,
    ) -> Course:
        course = Course(
            id=new_id("course"),
            title=title.strip(),
            description=description.strip(),
            legacy_id=legacy_id,
        )
        with self.transaction() as session:
            session.add(course)
        return course

    def list_courses(self, include_archived: bool = False) -> list[Course]:
        with self._sessions() as session:
            statement = select(Course).order_by(Course.created_at)
            if not include_archived:
                statement = statement.where(Course.status != "archived")
            return list(session.scalars(statement))

    def get_course(self, course_id: str) -> Optional[Course]:
        with self._sessions() as session:
            return session.get(Course, course_id)

    def get_training_profile_setting(
        self,
        scope_type: str,
        scope_id: str,
    ) -> Optional[TrainingProfileSetting]:
        with self._sessions() as session:
            return session.get(TrainingProfileSetting, (scope_type, scope_id))

    def set_training_profile(
        self,
        scope_type: str,
        scope_id: str,
        profile_key: str,
        config: Optional[dict[str, Any]] = None,
    ) -> None:
        if scope_type not in {"course", "module", "assignment"}:
            raise ValueError("Неизвестный уровень профиля тренировки.")
        if not profile_key.strip():
            raise ValueError("Профиль тренировки не задан.")
        with self.transaction() as session:
            setting = session.get(TrainingProfileSetting, (scope_type, scope_id))
            if setting is None:
                setting = TrainingProfileSetting(
                    scope_type=scope_type,
                    scope_id=scope_id,
                    profile_key=profile_key,
                    config=config or {},
                )
                session.add(setting)
            else:
                setting.profile_key = profile_key
                setting.config = config or {}
                setting.updated_at = utc_now()

    def clear_training_profile(self, scope_type: str, scope_id: str) -> None:
        with self.transaction() as session:
            setting = session.get(TrainingProfileSetting, (scope_type, scope_id))
            if setting is not None:
                session.delete(setting)

    def resolve_training_profile(
        self,
        module_id: str,
        assignment_id: Optional[str] = None,
    ) -> ProfilePreference:
        with self._sessions() as session:
            module = session.get(Module, module_id)
            if module is None:
                raise ValueError("Модуль не найден.")

            if assignment_id:
                assignment_setting = session.get(
                    TrainingProfileSetting,
                    ("assignment", assignment_id),
                )
                if assignment_setting is not None:
                    return ProfilePreference(
                        assignment_setting.profile_key,
                        dict(assignment_setting.config or {}),
                        "assignment",
                    )

            module_setting = session.get(
                TrainingProfileSetting,
                ("module", module_id),
            )
            if module_setting is not None:
                return ProfilePreference(
                    module_setting.profile_key,
                    dict(module_setting.config or {}),
                    "module",
                )

            course_setting = session.get(
                TrainingProfileSetting,
                ("course", module.course_id),
            )
            if course_setting is not None:
                return ProfilePreference(
                    course_setting.profile_key,
                    dict(course_setting.config or {}),
                    "course",
                )

            course = session.get(Course, module.course_id)
            if course is not None and course.legacy_id == "legacy:python":
                return ProfilePreference("python_practice", {}, "legacy_default")
            return ProfilePreference("auto", {}, "default")

    def add_module(
        self,
        course_id: str,
        title: str,
        description: str = "",
        scope_text: str = "",
        position: Optional[int] = None,
        legacy_id: Optional[str] = None,
    ) -> Module:
        with self.transaction() as session:
            if position is None:
                maximum = session.scalar(
                    select(func.max(Module.position)).where(Module.course_id == course_id)
                )
                position = int(maximum or 0) + 1

            module = Module(
                id=new_id("module"),
                course_id=course_id,
                position=position,
                title=title.strip(),
                description=description.strip(),
                scope_text=scope_text.strip(),
                legacy_id=legacy_id,
            )
            session.add(module)
        return module

    def list_modules(self, course_id: str) -> list[Module]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(Module)
                    .where(Module.course_id == course_id)
                    .order_by(Module.position)
                )
            )

    def get_module(self, module_id: str) -> Optional[Module]:
        with self._sessions() as session:
            return session.get(Module, module_id)

    def add_material(
        self,
        module_id: str,
        title: str,
        content: str,
        legacy_id: Optional[str] = None,
    ) -> Material:
        if not content.strip():
            raise ValueError("Материал не может быть пустым.")
        material = Material(
            id=new_id("material"),
            module_id=module_id,
            title=title.strip() or "Материал модуля",
            content=content.strip(),
            legacy_id=legacy_id,
        )
        with self.transaction() as session:
            session.add(material)
        return material

    def list_materials(self, module_id: str) -> list[Material]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(Material)
                    .where(Material.module_id == module_id, Material.status == "active")
                    .order_by(Material.created_at)
                )
            )

    def update_material(self, material_id: str, title: str, content: str) -> None:
        if not content.strip():
            raise ValueError("Материал не может быть пустым.")
        with self.transaction() as session:
            material = session.get(Material, material_id)
            if material is None:
                raise ValueError("Материал не найден.")
            material.title = title.strip() or "Материал модуля"
            material.content = content.strip()
            material.updated_at = utc_now()

    def upsert_knowledge_items(
        self,
        module_id: str,
        drafts: list[KnowledgeItemDraft],
    ) -> dict[str, str]:
        mapping: dict[str, str] = {}
        with self.transaction() as session:
            existing = {
                item.client_key: item
                for item in session.scalars(
                    select(KnowledgeItem).where(KnowledgeItem.module_id == module_id)
                )
            }
            active_keys = {draft.client_id for draft in drafts}
            for client_key, item in existing.items():
                if client_key not in active_keys:
                    item.status = "inactive"
                    item.updated_at = utc_now()
            for draft in drafts:
                item = existing.get(draft.client_id)
                if item is None:
                    item = KnowledgeItem(
                        id=new_id("knowledge"),
                        module_id=module_id,
                        client_key=draft.client_id,
                        kind=draft.kind.value,
                        title=draft.title,
                        description=draft.description,
                        source_excerpt=draft.source_excerpt,
                    )
                    session.add(item)
                else:
                    item.kind = draft.kind.value
                    item.title = draft.title
                    item.description = draft.description
                    item.source_excerpt = draft.source_excerpt
                    item.status = "active"
                    item.updated_at = utc_now()
                mapping[draft.client_id] = item.id
        return mapping

    def list_knowledge_items(self, module_id: str) -> list[KnowledgeItem]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(KnowledgeItem)
                    .where(
                        KnowledgeItem.module_id == module_id,
                        KnowledgeItem.status == "active",
                    )
                    .order_by(KnowledgeItem.kind, KnowledgeItem.created_at)
                )
            )

    def mark_module_studied(self, module_id: str, learned_date: date) -> None:
        with self.transaction() as session:
            module = session.get(Module, module_id)
            if module is None:
                raise ValueError("Модуль не найден.")
            if module.learned_date and module.learned_date != learned_date:
                pending = session.scalars(
                    select(ReviewAssignment).where(
                        ReviewAssignment.module_id == module_id,
                        ReviewAssignment.kind == "regular",
                        ReviewAssignment.status == "pending",
                    )
                )
                for assignment in pending:
                    assignment.status = "cancelled"
            module.learned_date = learned_date
            module.status = "learned"
            module.updated_at = utc_now()

            for slot in regular_review_slots(learned_date):
                key = f"{module_id}:{slot.idempotency_suffix}"
                exists = session.scalar(
                    select(ReviewAssignment.id).where(
                        ReviewAssignment.idempotency_key == key
                    )
                )
                if exists:
                    continue
                session.add(
                    ReviewAssignment(
                        id=new_id("assignment"),
                        module_id=module_id,
                        kind=slot.kind,
                        scheduled_date=slot.scheduled_date,
                        repetition_day=slot.repetition_day,
                        task_count=40,
                        idempotency_key=key,
                    )
                )

    def ensure_recovery_assignment(
        self,
        module_id: str,
        error_date: date,
        task_count: int,
        reason: str,
    ) -> ReviewAssignment:
        slot = recovery_slot(error_date, reason)
        key = f"{module_id}:{slot.idempotency_suffix}"
        with self.transaction() as session:
            existing = session.scalar(
                select(ReviewAssignment).where(ReviewAssignment.idempotency_key == key)
            )
            if existing:
                return existing
            assignment = ReviewAssignment(
                id=new_id("assignment"),
                module_id=module_id,
                kind="recovery",
                scheduled_date=slot.scheduled_date,
                task_count=task_count,
                reason=reason,
                idempotency_key=key,
            )
            session.add(assignment)
        return assignment

    def list_due_assignments(self, today: date) -> list[ReviewAssignment]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(ReviewAssignment)
                    .where(
                        ReviewAssignment.scheduled_date <= today,
                        ReviewAssignment.status.in_(["pending", "in_progress"]),
                    )
                    .order_by(ReviewAssignment.scheduled_date)
                )
            )

    def list_due_assignments_with_modules(
        self,
        today: date,
    ) -> list[tuple[ReviewAssignment, str]]:
        with self._sessions() as session:
            rows = session.execute(
                select(ReviewAssignment, Module.title)
                .join(Module, Module.id == ReviewAssignment.module_id)
                .where(
                    ReviewAssignment.scheduled_date <= today,
                    ReviewAssignment.status.in_(["pending", "in_progress"]),
                )
                .order_by(ReviewAssignment.scheduled_date)
            ).all()
        return [(assignment, module_title) for assignment, module_title in rows]

    def get_assignment(self, assignment_id: str) -> Optional[ReviewAssignment]:
        with self._sessions() as session:
            return session.get(ReviewAssignment, assignment_id)

    def get_review_session(self, session_id: str) -> Optional[ReviewSession]:
        with self._sessions() as session:
            return session.get(ReviewSession, session_id)

    def get_session_for_assignment(self, assignment_id: str) -> Optional[ReviewSession]:
        with self._sessions() as session:
            return session.scalar(
                select(ReviewSession).where(ReviewSession.assignment_id == assignment_id)
            )

    def create_session_with_tasks(
        self,
        assignment_id: str,
        tasks: list[TaskDraft],
        knowledge_by_client_key: dict[str, str],
        provider: str,
        model: str,
    ) -> ReviewSession:
        """Atomically persist a validated session and every generated task."""
        with self.transaction() as session:
            assignment = session.get(ReviewAssignment, assignment_id)
            if assignment is None:
                raise ValueError("Назначенное повторение не найдено.")

            existing = session.scalar(
                select(ReviewSession).where(ReviewSession.assignment_id == assignment_id)
            )
            if existing:
                return existing

            if len(tasks) != assignment.task_count:
                raise ValueError(
                    f"Нельзя сохранить {len(tasks)} заданий: ожидалось {assignment.task_count}."
                )

            review_session = ReviewSession(
                id=new_id("session"),
                module_id=assignment.module_id,
                assignment_id=assignment.id,
                kind=assignment.kind,
                scheduled_date=assignment.scheduled_date,
                repetition_day=assignment.repetition_day,
            )
            session.add(review_session)
            session.flush()

            for position, draft in enumerate(tasks, start=1):
                task = Task(
                    id=new_id("task"),
                    session_id=review_session.id,
                    module_id=assignment.module_id,
                    position=position,
                    format=draft.format.value,
                    difficulty=draft.difficulty,
                    prompt=draft.prompt,
                    stimulus=draft.stimulus,
                    options=draft.options,
                    correct_answer=draft.correct_answer,
                    answer_guidance=draft.answer_guidance,
                    provider_metadata={"provider": provider, "model": model},
                )
                session.add(task)
                for client_key in draft.knowledge_client_ids:
                    knowledge_id = knowledge_by_client_key.get(client_key)
                    if knowledge_id is None:
                        raise ValueError(f"Неизвестный knowledge ID: {client_key}")
                    session.add(
                        TaskKnowledgeLink(
                            task_id=task.id,
                            knowledge_item_id=knowledge_id,
                        )
                    )

            assignment.status = "in_progress"
        return review_session

    def record_generation_failure(
        self,
        module_id: str,
        provider: str,
        error_message: str,
        assignment_id: Optional[str] = None,
    ) -> None:
        with self.transaction() as session:
            session.add(
                GenerationFailure(
                    id=new_id("failure"),
                    assignment_id=assignment_id,
                    module_id=module_id,
                    provider=provider,
                    error_message=error_message[:5000],
                )
            )

    def list_tasks(self, session_id: str) -> list[Task]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(Task)
                    .where(Task.session_id == session_id)
                    .order_by(Task.position)
                )
            )

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._sessions() as session:
            return session.get(Task, task_id)

    def get_latest_attempt(self, task_id: str) -> Optional[Attempt]:
        with self._sessions() as session:
            return session.scalar(
                select(Attempt)
                .where(Attempt.task_id == task_id)
                .order_by(Attempt.created_at.desc(), Attempt.id.desc())
                .limit(1)
            )

    def get_knowledge_items_by_ids(self, knowledge_ids: list[str]) -> list[KnowledgeItem]:
        if not knowledge_ids:
            return []
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(KnowledgeItem).where(KnowledgeItem.id.in_(knowledge_ids))
                )
            )

    def task_knowledge_ids(self, task_id: str) -> list[str]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(TaskKnowledgeLink.knowledge_item_id).where(
                        TaskKnowledgeLink.task_id == task_id
                    )
                )
            )

    def add_attempt(
        self,
        task_id: str,
        user_answer: Any,
        verdict: str,
        feedback: str,
        error_type: str = "",
        error_summary: str = "",
        legacy_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> Attempt:
        with self.transaction() as session:
            task = session.get(Task, task_id)
            if task is None:
                raise ValueError("Задание не найдено.")
            attempt = Attempt(
                id=new_id("attempt"),
                task_id=task.id,
                session_id=task.session_id,
                user_answer=user_answer,
                verdict=verdict,
                feedback=feedback,
                error_type=error_type,
                error_summary=error_summary,
                legacy_id=legacy_id,
                created_at=created_at or utc_now(),
            )
            session.add(attempt)
            task.status = verdict
        return attempt

    def set_task_status(self, task_id: str, status: str) -> None:
        allowed = {
            "new",
            "correct",
            "partially_correct",
            "incorrect",
            "skipped",
            "abandoned",
            "bad_task",
        }
        if status not in allowed:
            raise ValueError(f"Неизвестный статус задания: {status}")
        with self.transaction() as session:
            task = session.get(Task, task_id)
            if task is None:
                raise ValueError("Задание не найдено.")
            task.status = status

    def add_task_feedback(self, task_id: str, issue_type: str, comment: str = "") -> None:
        with self.transaction() as session:
            task = session.get(Task, task_id)
            if task is None:
                raise ValueError("Задание не найдено.")
            session.add(
                TaskFeedback(
                    id=new_id("feedback"),
                    task_id=task_id,
                    issue_type=issue_type,
                    comment=comment,
                )
            )
            task.status = "bad_task"

    def complete_session_if_ready(self, session_id: str) -> bool:
        closed = {"correct", "abandoned", "bad_task"}
        with self.transaction() as session:
            review_session = session.get(ReviewSession, session_id)
            if review_session is None:
                raise ValueError("Сессия не найдена.")
            tasks = list(
                session.scalars(select(Task).where(Task.session_id == session_id))
            )
            if not tasks or any(task.status not in closed for task in tasks):
                return False
            review_session.status = "completed"
            review_session.completed_at = utc_now()
            if review_session.assignment_id:
                assignment = session.get(ReviewAssignment, review_session.assignment_id)
                if assignment:
                    assignment.status = "completed"
            return True

    def get_learning_attempts(self, module_id: str) -> list[dict[str, Any]]:
        with self._sessions() as session:
            rows = session.execute(
                select(Attempt, TaskKnowledgeLink.knowledge_item_id)
                .join(Task, Task.id == Attempt.task_id)
                .join(TaskKnowledgeLink, TaskKnowledgeLink.task_id == Task.id)
                .where(Task.module_id == module_id)
                .order_by(Attempt.created_at)
            ).all()

        grouped: dict[str, dict[str, Any]] = {}
        for attempt, knowledge_id in rows:
            row = grouped.setdefault(
                attempt.id,
                {
                    "attempt_id": attempt.id,
                    "verdict": attempt.verdict,
                    "feedback": attempt.feedback,
                    "error_type": attempt.error_type,
                    "error_summary": attempt.error_summary,
                    "created_at": attempt.created_at,
                    "knowledge_ids": [],
                },
            )
            row["knowledge_ids"].append(knowledge_id)
        return list(grouped.values())

    def get_progress_overview(self) -> list[ProgressRow]:
        with self._sessions() as session:
            rows = session.execute(
                select(
                    Course.id,
                    Course.title,
                    Module.id,
                    Module.position,
                    Module.title,
                    Module.status,
                    func.count(Attempt.id),
                )
                .select_from(Course)
                .outerjoin(Module, Module.course_id == Course.id)
                .outerjoin(Task, Task.module_id == Module.id)
                .outerjoin(Attempt, Attempt.task_id == Task.id)
                .where(Course.status != "archived")
                .group_by(
                    Course.id,
                    Course.title,
                    Course.created_at,
                    Module.id,
                    Module.position,
                    Module.title,
                    Module.status,
                )
                .order_by(Course.created_at, Module.position)
            ).all()
        return [
            ProgressRow(
                course_id=course_id,
                course_title=course_title,
                module_id=module_id,
                module_position=module_position,
                module_title=module_title,
                module_status=module_status,
                attempt_count=int(attempt_count or 0),
            )
            for (
                course_id,
                course_title,
                module_id,
                module_position,
                module_title,
                module_status,
                attempt_count,
            ) in rows
        ]

    def get_recent_history(self, module_id: str, limit: int = 30) -> list[dict[str, Any]]:
        with self._sessions() as session:
            rows = session.execute(
                select(Attempt, Task)
                .join(Task, Task.id == Attempt.task_id)
                .where(Task.module_id == module_id)
                .order_by(Attempt.created_at.desc())
                .limit(limit)
            ).all()
        return [
            {
                "task_format": task.format,
                "task_prompt": task.prompt,
                "task_stimulus": task.stimulus,
                "verdict": attempt.verdict,
                "feedback": attempt.feedback,
                "error_type": attempt.error_type,
                "error_summary": attempt.error_summary,
                "created_at": attempt.created_at.isoformat(),
            }
            for attempt, task in reversed(rows)
        ]

    def get_recent_task_feedback(
        self,
        module_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._sessions() as session:
            rows = session.execute(
                select(TaskFeedback, Task)
                .join(Task, Task.id == TaskFeedback.task_id)
                .where(Task.module_id == module_id)
                .order_by(TaskFeedback.created_at.desc())
                .limit(limit)
            ).all()
        return [
            {
                "task_format": task.format,
                "task_prompt": task.prompt,
                "task_stimulus": task.stimulus,
                "task_options": task.options,
                "issue_type": feedback.issue_type,
                "comment": feedback.comment,
                "created_at": feedback.created_at.isoformat(),
            }
            for feedback, task in reversed(rows)
        ]
