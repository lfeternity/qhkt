from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Timestamped:
    create_time: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    update_time: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)


class Conversation(Timestamped, Base):
    __tablename__ = "ai_conversation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), default="新的学习对话", nullable=False)
    scene: Mapped[str] = mapped_column(String(32), default="LEARNING_ASSISTANT", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(String(64), default="learning-agent-v1", nullable=False)

    __table_args__ = (Index("idx_conversation_user_update", "user_id", "update_time"),)


class Message(Timestamped, Base):
    __tablename__ = "ai_message"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("ai_conversation.id"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    model: Mapped[str | None] = mapped_column(String(80))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    finish_reason: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (Index("idx_message_conversation_time", "conversation_id", "create_time"),)


class Citation(Timestamped, Base):
    __tablename__ = "ai_citation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("ai_message.id"), index=True)
    chunk_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(80))
    course_id: Mapped[int | None] = mapped_column(Integer)
    chapter_id: Mapped[int | None] = mapped_column(Integer)
    section_id: Mapped[int | None] = mapped_column(Integer)
    start_moment: Mapped[int | None] = mapped_column(Integer)
    end_moment: Mapped[int | None] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    score: Mapped[float | None] = mapped_column(Float)


class ToolCall(Timestamped, Base):
    __tablename__ = "ai_tool_call"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    arguments_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))


class PendingAction(Timestamped, Base):
    __tablename__ = "ai_pending_action"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    expire_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    result_message: Mapped[str | None] = mapped_column(String(300))
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Feedback(Timestamped, Base):
    __tablename__ = "ai_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    message_id: Mapped[str] = mapped_column(String(36), nullable=False)
    rating: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (UniqueConstraint("user_id", "message_id", name="uk_feedback_user_message"),)


class KnowledgeDocument(Timestamped, Base):
    __tablename__ = "ai_knowledge_document"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[int | None] = mapped_column(Integer, index=True)
    chapter_id: Mapped[int | None] = mapped_column(Integer)
    section_id: Mapped[int | None] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT", nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), default="ENROLLED", nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500))
    object_file_id: Mapped[str | None] = mapped_column(String(80), index=True)
    object_key: Mapped[str | None] = mapped_column(String(500))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    file_size: Mapped[int | None] = mapped_column(Integer)
    checksum: Mapped[str | None] = mapped_column(String(64))


class KnowledgeChunk(Timestamped, Base):
    __tablename__ = "ai_knowledge_chunk"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    course_id: Mapped[int | None] = mapped_column(Integer, index=True)
    chapter_id: Mapped[int | None] = mapped_column(Integer)
    section_id: Mapped[int | None] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    start_moment: Mapped[int | None] = mapped_column(Integer)
    end_moment: Mapped[int | None] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    embedding_model: Mapped[str | None] = mapped_column(String(80))


class IngestionJob(Timestamped, Base):
    __tablename__ = "ai_ingestion_job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    requested_by: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    stage: Mapped[str] = mapped_column(String(20), default="QUEUED", nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_attempt_time: Mapped[datetime | None] = mapped_column(DateTime)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    started_time: Mapped[datetime | None] = mapped_column(DateTime)
    completed_time: Mapped[datetime | None] = mapped_column(DateTime)


class PromptVersion(Timestamped, Base):
    __tablename__ = "ai_prompt_version"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    prompt_key: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT", nullable=False)
    publisher_id: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (UniqueConstraint("prompt_key", "version", name="uk_prompt_key_version"),)


class UserProfile(Timestamped, Base):
    __tablename__ = "ai_user_profile"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    learning_goal: Mapped[str | None] = mapped_column(String(500))
    preferred_style: Mapped[str | None] = mapped_column(String(32))
    weekly_hours: Mapped[int | None] = mapped_column(Integer)
    consented: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MemoryFact(Timestamped, Base):
    """A consented, bounded long-term learning fact owned by one user."""

    __tablename__ = "ai_memory_fact"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    fact_key: Mapped[str] = mapped_column(String(64), nullable=False)
    fact_value: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(String(36), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    expire_time: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_time: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (Index("idx_memory_fact_user_key", "user_id", "fact_key"),)


class ModelUsage(Timestamped, Base):
    __tablename__ = "ai_model_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    scene: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_micros: Mapped[int | None] = mapped_column(Integer)
    price_version: Mapped[str] = mapped_column(String(32), default="unpriced", nullable=False)


def model_to_dict(value: Any) -> dict[str, Any]:
    return {column.name: getattr(value, column.name) for column in value.__table__.columns}
