from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)


class EventStreamStore:
    """Bounded replay buffer shared by SSE and WebSocket transports."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._redis: Any | None = None
        self._local: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=256))
        self._local_sequence: dict[str, int] = defaultdict(int)
        if settings.redis_url:
            try:
                from redis.asyncio import Redis

                self._redis = Redis.from_url(settings.redis_url, password=settings.redis_password or None, decode_responses=True)
            except ImportError:
                logger.warning("redis package unavailable; event replay uses process-local buffer")

    def _key(self, user_id: int, conversation_id: str) -> str:
        return f"{self.settings.app_env}:agent:events:{user_id}:{conversation_id}"

    async def append(self, user_id: int, conversation_id: str, event_id: str | None, event: dict[str, Any]) -> str:
        key = self._key(user_id, conversation_id)
        if self._redis:
            sequence_key = f"{key}:sequence"
            event_id = event_id or str(await self._redis.incr(sequence_key))
            await self._redis.xadd(key, {"eventId": event_id, "payload": json.dumps(event, ensure_ascii=False, default=str)}, maxlen=256, approximate=True)
            await self._redis.expire(key, self.settings.graph_checkpoint_ttl_seconds)
            await self._redis.expire(sequence_key, self.settings.graph_checkpoint_ttl_seconds)
        else:
            event_id = event_id or str(self._local_sequence[key] + 1)
            self._local_sequence[key] = max(self._local_sequence[key], int(event_id))
            self._local[key].append({"eventId": event_id, **event})
        return event_id

    async def replay(self, user_id: int, conversation_id: str, after: str | None = None) -> list[dict[str, Any]]:
        key = self._key(user_id, conversation_id)
        if self._redis:
            rows = await self._redis.xrange(key, min="-", max="+")
            result: list[dict[str, Any]] = []
            def is_after(candidate: str, cursor: str) -> bool:
                try:
                    return int(candidate) > int(cursor)
                except (TypeError, ValueError):
                    return candidate > cursor

            for _, fields in rows:
                if after and not is_after(str(fields.get("eventId")), after):
                    continue
                try:
                    value = json.loads(fields.get("payload", "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if isinstance(value, dict):
                    value["eventId"] = fields.get("eventId")
                    result.append(value)
            return result
        if not after:
            return list(self._local.get(key, ()))
        try:
            cursor = int(after)
            return [item for item in self._local.get(key, ()) if int(item.get("eventId", 0)) > cursor]
        except (TypeError, ValueError):
            return [item for item in self._local.get(key, ()) if str(item.get("eventId")) > after]

    async def delete(self, user_id: int, conversation_id: str) -> None:
        key = self._key(user_id, conversation_id)
        if self._redis:
            await self._redis.delete(key)
        self._local.pop(key, None)
        self._local_sequence.pop(key, None)

    async def close(self) -> None:
        if self._redis and hasattr(self._redis, "aclose"):
            await self._redis.aclose()


class WebSocketTicketStore:
    """One-time, user/conversation-bound tickets with Redis-backed sharing."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._redis: Any | None = None
        self._local: dict[str, dict[str, Any]] = {}
        if settings.redis_url:
            try:
                from redis.asyncio import Redis

                self._redis = Redis.from_url(settings.redis_url, password=settings.redis_password or None, decode_responses=True)
            except ImportError:
                logger.warning("redis package unavailable; WebSocket tickets use process-local storage")

    def _key(self, ticket: str) -> str:
        return f"{self.settings.app_env}:agent:ws-ticket:{ticket}"

    async def issue(self, ticket: str, user_id: int, conversation_id: str, ttl: int = 30) -> None:
        payload = json.dumps({"userId": user_id, "conversationId": conversation_id}, ensure_ascii=False)
        if self._redis:
            await self._redis.set(self._key(ticket), payload, ex=ttl)
        else:
            self._local[ticket] = {"userId": user_id, "conversationId": conversation_id, "expire": time.monotonic() + ttl}

    async def consume(self, ticket: str) -> dict[str, Any] | None:
        if self._redis:
            value = await self._redis.getdel(self._key(ticket))
            if not value:
                return None
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                return None
            return parsed if isinstance(parsed, dict) else None
        record = self._local.pop(ticket, None)
        if not record or record["expire"] <= time.monotonic():
            return None
        return record

    async def close(self) -> None:
        if self._redis and hasattr(self._redis, "aclose"):
            await self._redis.aclose()
