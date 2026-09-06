from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.persistence.models import Citation, Conversation, Feedback, Message, now_utc
from app.security.identity import Identity


def iso(value: Any) -> str | None:
    return value.isoformat() if value else None


async def create_conversation(session: AsyncSession, identity: Identity, title: str | None, scene: str | None, settings: Settings) -> dict[str, Any]:
    conversation = Conversation(user_id=identity.user_id, title=(title or "新的学习对话").strip()[:120], scene=(scene or "LEARNING_ASSISTANT").strip().upper()[:32], prompt_version=settings.prompt_version)
    session.add(conversation)
    await session.commit()
    return conversation_dict(conversation)


async def list_conversations(session: AsyncSession, identity: Identity) -> list[dict[str, Any]]:
    result = await session.execute(select(Conversation).where(Conversation.user_id == identity.user_id, Conversation.status == "ACTIVE").order_by(Conversation.update_time.desc()).limit(50))
    return [conversation_dict(item) for item in result.scalars()]


async def get_owned_conversation(session: AsyncSession, identity: Identity, conversation_id: str) -> Conversation:
    result = await session.execute(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == identity.user_id, Conversation.status == "ACTIVE"))
    value = result.scalar_one_or_none()
    if not value:
        raise LookupError("会话不存在")
    return value


async def list_messages(session: AsyncSession, identity: Identity, conversation_id: str) -> list[dict[str, Any]]:
    await get_owned_conversation(session, identity, conversation_id)
    result = await session.execute(select(Message).where(Message.conversation_id == conversation_id, Message.role != "SYSTEM").order_by(Message.create_time.asc()))
    messages = list(result.scalars())
    output: list[dict[str, Any]] = []
    for message in messages:
        citation_result = await session.execute(select(Citation).where(Citation.message_id == message.id).order_by(Citation.id.asc()))
        output.append({"id": message.id, "role": message.role, "content": message.content, "createTime": iso(message.create_time), "citations": [citation_dict(item) for item in citation_result.scalars()]})
    return output


async def delete_conversation(session: AsyncSession, identity: Identity, conversation_id: str) -> None:
    conversation = await get_owned_conversation(session, identity, conversation_id)
    message_result = await session.execute(select(Message.id).where(Message.conversation_id == conversation_id))
    message_ids = [item[0] for item in message_result.all()]
    if message_ids:
        await session.execute(delete(Citation).where(Citation.message_id.in_(message_ids)))
        await session.execute(delete(Feedback).where(Feedback.message_id.in_(message_ids)))
        await session.execute(delete(Message).where(Message.conversation_id == conversation_id))
    conversation.status = "DELETED"
    conversation.update_time = now_utc()
    await session.commit()


async def save_message(session: AsyncSession, identity: Identity, conversation_id: str, role: str, content: str = "") -> Message:
    await get_owned_conversation(session, identity, conversation_id)
    message = Message(user_id=identity.user_id, conversation_id=conversation_id, role=role, content=content)
    session.add(message)
    await session.flush()
    return message


async def update_assistant(session: AsyncSession, message_id: str, content: str, model: str, finish_reason: str, latency_ms: int, usage: dict[str, Any]) -> None:
    message = await session.get(Message, message_id)
    if not message:
        return
    message.content = content
    message.model = model
    message.finish_reason = finish_reason
    message.latency_ms = latency_ms
    message.input_tokens = int(usage.get("inputTokens") or usage.get("prompt_tokens") or 0)
    message.output_tokens = int(usage.get("outputTokens") or usage.get("completion_tokens") or 0)
    await session.flush()


async def save_citations(session: AsyncSession, message_id: str, citations: list[dict[str, Any]]) -> None:
    for item in citations:
        session.add(Citation(message_id=message_id, chunk_id=str(item.get("chunkId") or ""), source_type=str(item.get("sourceType") or "COURSE"), source_id=item.get("sourceId"), course_id=item.get("courseId"), chapter_id=item.get("chapterId"), section_id=item.get("sectionId"), start_moment=item.get("startMoment"), end_moment=item.get("endMoment"), page_number=item.get("page"), title=str(item.get("title") or "课程资料"), score=item.get("score")))


async def save_feedback(session: AsyncSession, identity: Identity, message_id: str, rating: str, reason: str | None, comment: str | None) -> None:
    result = await session.execute(select(Message).where(Message.id == message_id, Message.user_id == identity.user_id))
    if not result.scalar_one_or_none():
        raise LookupError("消息不存在")
    existing = (await session.execute(select(Feedback).where(Feedback.user_id == identity.user_id, Feedback.message_id == message_id))).scalar_one_or_none()
    if existing:
        existing.rating, existing.reason, existing.comment = rating, reason, comment
    else:
        session.add(Feedback(user_id=identity.user_id, message_id=message_id, rating=rating, reason=reason, comment=comment))
    await session.commit()


def conversation_dict(value: Conversation) -> dict[str, Any]:
    return {"id": value.id, "title": value.title, "scene": value.scene, "status": value.status, "createTime": iso(value.create_time), "updateTime": iso(value.update_time)}


def citation_dict(value: Citation) -> dict[str, Any]:
    return {"chunkId": value.chunk_id, "sourceType": value.source_type, "sourceId": value.source_id, "courseId": value.course_id, "chapterId": value.chapter_id, "sectionId": value.section_id, "startMoment": value.start_moment, "endMoment": value.end_moment, "page": value.page_number, "title": value.title, "score": value.score}
