from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.persistence.models import MemoryFact, Message, now_utc

logger = logging.getLogger(__name__)


def build_summary(messages: Iterable[Message], max_chars: int = 4000) -> str | None:
    lines: list[str] = []
    for message in messages:
        content = (message.content or "").strip()
        if content and message.role in {"USER", "ASSISTANT"}:
            lines.append(f"{message.role.lower()}: {content}")
    if not lines:
        return None
    return "\n".join(lines)[-max_chars:]


def estimate_tokens(value: str) -> int:
    """Conservative multilingual estimate used when a tokenizer is unavailable."""
    if not value:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", value))
    other = len(value) - cjk
    return max(1, cjk + (other + 3) // 4)


def build_token_bounded_summary(messages: Iterable[Message], max_tokens: int = 1000) -> str | None:
    lines: list[str] = []
    used = 0
    for message in messages:
        content = (message.content or "").strip()
        if not content or message.role not in {"USER", "ASSISTANT"}:
            continue
        line = f"{message.role.lower()}: {content}"
        cost = estimate_tokens(line)
        if used + cost > max_tokens:
            break
        lines.append(line)
        used += cost
    return "\n".join(lines) if lines else None


class RedisConversationMemory:
    """Redis-backed short-term state with explicit TTL and user namespacing."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._redis: Any | None = None
        if settings.redis_url and settings.redis_memory_enabled:
            try:
                from redis.asyncio import Redis

                self._redis = Redis.from_url(settings.redis_url, password=settings.redis_password or None, decode_responses=True)
            except ImportError:
                logger.warning("redis package unavailable; short-term memory disabled")

    def _key(self, user_id: int, conversation_id: str) -> str:
        return f"{self.settings.app_env}:agent:memory:{user_id}:{conversation_id}"

    async def save(self, user_id: int, conversation_id: str, state: dict[str, Any]) -> None:
        if not self._redis:
            return
        payload = json.dumps(state, ensure_ascii=False, default=str)
        await self._redis.set(self._key(user_id, conversation_id), payload, ex=self.settings.graph_checkpoint_ttl_seconds)

    async def load(self, user_id: int, conversation_id: str) -> dict[str, Any] | None:
        if not self._redis:
            return None
        value = await self._redis.get(self._key(user_id, conversation_id))
        if not value:
            return None
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    async def delete(self, user_id: int, conversation_id: str) -> None:
        if self._redis:
            await self._redis.delete(self._key(user_id, conversation_id))

    async def delete_user(self, user_id: int) -> None:
        if not self._redis:
            return
        pattern = f"{self.settings.app_env}:agent:memory:{user_id}:*"
        keys = [key async for key in self._redis.scan_iter(match=pattern)]
        if keys:
            await self._redis.delete(*keys)

    async def close(self) -> None:
        if self._redis and hasattr(self._redis, "aclose"):
            await self._redis.aclose()


class SqlAlchemyChatMessageHistory(BaseChatMessageHistory):
    """LangChain history facade backed by the existing auditable message table."""

    def __init__(self, session: AsyncSession, user_id: int, conversation_id: str) -> None:
        self.session = session
        self.user_id = user_id
        self.conversation_id = conversation_id

    @property
    def messages(self) -> list[BaseMessage]:
        # Synchronous access is intentionally unsupported in the async service.
        raise RuntimeError("请使用 aget_messages")

    async def aget_messages(self) -> list[BaseMessage]:
        result = await self.session.execute(select(Message).where(
            Message.user_id == self.user_id,
            Message.conversation_id == self.conversation_id,
            Message.role.in_(("USER", "ASSISTANT")),
        ).order_by(Message.create_time.asc()))
        converted: list[BaseMessage] = []
        for item in result.scalars():
            if item.role == "USER":
                converted.append(HumanMessage(content=item.content))
            elif item.role == "ASSISTANT":
                converted.append(AIMessage(content=item.content))
            else:
                converted.append(SystemMessage(content=item.content))
        return converted

    async def aadd_messages(self, messages: list[BaseMessage]) -> None:
        for message in messages:
            role = "USER" if isinstance(message, HumanMessage) else "ASSISTANT" if isinstance(message, AIMessage) else "SYSTEM"
            self.session.add(Message(user_id=self.user_id, conversation_id=self.conversation_id, role=role, content=str(message.content)))
        await self.session.flush()

    async def aclear(self) -> None:
        await self.session.execute(delete(Message).where(Message.user_id == self.user_id, Message.conversation_id == self.conversation_id))

    def clear(self) -> None:
        """Synchronous API is unavailable because this history uses an async session."""
        raise RuntimeError("请使用 aclear")


async def list_memory_facts(session: AsyncSession, user_id: int) -> list[MemoryFact]:
    now = now_utc()
    result = await session.execute(select(MemoryFact).where(
        MemoryFact.user_id == user_id,
        MemoryFact.deleted_time.is_(None),
        (MemoryFact.expire_time.is_(None) | (MemoryFact.expire_time > now)),
    ).order_by(MemoryFact.update_time.desc()).limit(100))
    return list(result.scalars())


async def upsert_memory_fact(
    session: AsyncSession,
    user_id: int,
    fact_key: str,
    fact_value: str,
    source_message_id: str | None = None,
    confidence: float = 1.0,
    expire_time: datetime | None = None,
) -> MemoryFact:
    if fact_key not in {"learning_goal", "preferred_style", "weekly_hours", "difficulty", "topic"}:
        raise ValueError("不允许保存该类型的长期记忆")
    result = await session.execute(select(MemoryFact).where(MemoryFact.user_id == user_id, MemoryFact.fact_key == fact_key, MemoryFact.deleted_time.is_(None)))
    fact = result.scalar_one_or_none()
    if fact is None:
        fact = MemoryFact(user_id=user_id, fact_key=fact_key, fact_value=fact_value[:1000], source_message_id=source_message_id, confidence=max(0.0, min(1.0, confidence)), expire_time=expire_time)
        session.add(fact)
    else:
        fact.fact_value = fact_value[:1000]
        fact.source_message_id = source_message_id
        fact.confidence = max(0.0, min(1.0, confidence))
        fact.expire_time = expire_time
        fact.deleted_time = None
    await session.flush()
    return fact


async def delete_user_memory(session: AsyncSession, user_id: int) -> None:
    await session.execute(delete(MemoryFact).where(MemoryFact.user_id == user_id))
