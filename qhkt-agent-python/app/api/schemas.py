from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    scene: str | None = Field(default="LEARNING_ASSISTANT", max_length=32)


class ChatContext(BaseModel):
    courseId: int | None = None
    chapterId: int | None = None
    sectionId: int | None = None
    playMoment: int | None = Field(default=None, ge=0, le=86400)
    page: str | None = Field(default=None, max_length=32)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    context: ChatContext | None = None

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("问题不能为空")
        return value


class FeedbackRequest(BaseModel):
    rating: str = Field(min_length=1, max_length=16)
    reason: str | None = Field(default=None, max_length=64)
    comment: str | None = Field(default=None, max_length=500)


class KnowledgeDocumentRequest(BaseModel):
    courseId: int = Field(gt=0)
    chapterId: int | None = None
    sectionId: int | None = None
    sourceType: str = Field(default="COURSE", max_length=32)
    sourceId: str | None = Field(default=None, max_length=80)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=500000)
    visibility: str = Field(default="ENROLLED", max_length=16)
    sourceUrl: str | None = Field(default=None, max_length=500)


class ProfileRequest(BaseModel):
    learningGoal: str | None = Field(default=None, max_length=500)
    preferredStyle: str | None = Field(default=None, max_length=32)
    weeklyHours: int | None = Field(default=None, ge=0, le=168)
    consented: bool = False


class PromptRequest(BaseModel):
    promptKey: str = Field(default="learning-assistant", min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=100000)


def context_dict(value: ChatContext | None) -> dict[str, Any]:
    if value is None:
        return {}
    return {"courseId": value.courseId, "chapterId": value.chapterId, "sectionId": value.sectionId, "playMoment": value.playMoment, "page": value.page}
