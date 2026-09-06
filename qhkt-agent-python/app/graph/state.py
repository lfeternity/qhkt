from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field


class PlanStepModel(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    goal: str = Field(min_length=1, max_length=4000)
    capability: str = Field(min_length=1, max_length=32)
    dependencies: list[str] = Field(default_factory=list)
    status: str = "PENDING"


class ExecutionPlanModel(BaseModel):
    steps: list[PlanStepModel] = Field(min_length=1, max_length=12)
    current_step: int = Field(default=0, ge=0)
    status: str = "RUNNING"


class CitationModel(BaseModel):
    chunkId: str
    title: str = ""
    content: str = ""
    sourceType: str = ""
    sourceId: str | None = None
    courseId: int | None = None
    chapterId: int | None = None
    sectionId: int | None = None
    startMoment: int | None = None
    endMoment: int | None = None
    page: int | None = None
    score: float = 0.0


class FinalAnswerModel(BaseModel):
    content: str = ""
    citations: list[CitationModel] = Field(default_factory=list)
    finish_reason: str = "STOP"


class AgentEventModel(BaseModel):
    name: str
    data: dict[str, Any] = Field(default_factory=dict)


class PlanStep(TypedDict, total=False):
    id: str
    goal: str
    capability: str
    dependencies: list[str]
    status: str


class ExecutionPlan(TypedDict, total=False):
    steps: list[PlanStep]
    current_step: int
    status: str


class AgentState(TypedDict, total=False):
    runtime_key: str
    system_prompt: str
    prompt_version: str | None
    conversation_id: str
    user_id: int
    user_message: str
    page_context: dict[str, Any]
    history: list[BaseMessage]
    messages: list[BaseMessage]
    plan: ExecutionPlan
    step_count: int
    tool_retry_counts: dict[str, int]
    pending_tool_calls: list[dict[str, Any]]
    tool_observations: list[dict[str, Any]]
    answer: str
    citations: list[dict[str, Any]]
    usage: dict[str, Any]
    model: str
    finish_reason: str
    done: bool
    # Node events are append-only so checkpoints retain the full audit trail.
    events: Annotated[list[dict[str, Any]], add]
    error: str | None
