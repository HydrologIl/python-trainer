from __future__ import annotations

from enum import Enum
from typing import Any, Union

from pydantic import BaseModel, Field, field_validator


class KnowledgeKind(str, Enum):
    THEORY = "theory"
    SKILL = "skill"


class SessionKind(str, Enum):
    REGULAR = "regular"
    RECOVERY = "recovery"


class Verdict(str, Enum):
    CORRECT = "correct"
    PARTIALLY_CORRECT = "partially_correct"
    INCORRECT = "incorrect"


class TaskFormat(str, Enum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    MATCHING = "matching"
    ORDERING = "ordering"
    FILL_BLANK = "fill_blank"
    OPEN_ANSWER = "open_answer"
    DEBUG = "debug"
    OUTPUT_PREDICTION = "output_prediction"
    WRITE_CODE = "write_code"
    WRITE_CONFIG = "write_config"
    PRACTICAL_OPEN = "practical_open"


LOCALLY_GRADED_FORMATS = {
    TaskFormat.SINGLE_CHOICE,
    TaskFormat.MULTIPLE_CHOICE,
    TaskFormat.TRUE_FALSE,
    TaskFormat.MATCHING,
    TaskFormat.ORDERING,
    TaskFormat.FILL_BLANK,
}


class KnowledgeItemDraft(BaseModel):
    client_id: str = Field(min_length=1, max_length=80)
    kind: KnowledgeKind
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=2000)
    source_excerpt: str = Field(default="", max_length=3000)


class MaterialAnalysis(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    items: list[KnowledgeItemDraft] = Field(min_length=1, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=20)


class TaskDraft(BaseModel):
    format: TaskFormat
    difficulty: int = Field(ge=1, le=5)
    prompt: str = Field(min_length=1, max_length=5000)
    stimulus: str = Field(default="", max_length=12000)
    options: list[str] = Field(default_factory=list, max_length=20)
    correct_answer: Union[str, bool, list[str], dict[str, str], None] = None
    answer_guidance: str = Field(default="", max_length=5000)
    knowledge_client_ids: list[str] = Field(min_length=1, max_length=10)

    @field_validator("options")
    @classmethod
    def strip_options(cls, value: list[str]) -> list[str]:
        return [str(item).strip() for item in value if str(item).strip()]


class TaskBatch(BaseModel):
    tasks: list[TaskDraft] = Field(min_length=1, max_length=40)


class GradingResult(BaseModel):
    verdict: Verdict
    feedback: str = Field(min_length=1, max_length=5000)
    error_type: str = Field(default="", max_length=120)
    error_summary: str = Field(default="", max_length=1000)


class KnowledgeProfile(BaseModel):
    knowledge_id: str
    title: str
    kind: KnowledgeKind
    mastery: float = Field(ge=0.0, le=1.0)
    attempts: int = Field(ge=0)
    recent_errors: list[str] = Field(default_factory=list, max_length=10)
