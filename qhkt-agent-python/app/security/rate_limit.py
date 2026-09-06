from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque

from fastapi import HTTPException

from app.config import Settings

try:
    from redis.asyncio import Redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - dependency is installed in normal deployments
    Redis = None  # type: ignore[assignment,misc]
    RedisError = Exception  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._requests: dict[int, deque[float]] = defaultdict(deque)
        self._messages: dict[int, deque[float]] = defaultdict(deque)
        self._active: dict[int, int] = defaultdict(int)
        self._local_fallback_active: dict[int, int] = defaultdict(int)
        self._lock = asyncio.Lock()
        self._redis = (
            Redis.from_url(
                settings.redis_url,
                password=settings.redis_password or None,
                decode_responses=True,
            )
            if settings.redis_url and Redis
            else None
        )

    async def acquire(self, user_id: int) -> None:
        if not self.settings.rate_limit_enabled:
            return
        if self._redis:
            try:
                await self._acquire_redis(user_id)
                return
            except RedisError:
                logger.warning("Redis rate limiter unavailable; using local limiter", exc_info=True)
                self._local_fallback_active[user_id] += 1
        now = time.monotonic()
        async with self._lock:
            requests = self._requests[user_id]
            messages = self._messages[user_id]
            while requests and now - requests[0] >= 60:
                requests.popleft()
            while messages and now - messages[0] >= 86400:
                messages.popleft()
            try:
                if len(requests) >= self.settings.requests_per_minute:
                    raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试")
                if len(messages) >= self.settings.messages_per_day:
                    raise HTTPException(status_code=429, detail="今日对话次数已达上限")
                if self._active[user_id] >= self.settings.concurrent_streams:
                    raise HTTPException(status_code=429, detail="同时进行的对话过多")
            except HTTPException:
                self._local_fallback_active[user_id] = max(0, self._local_fallback_active[user_id] - 1)
                raise
            requests.append(now)
            messages.append(now)
            self._active[user_id] += 1

    async def release(self, user_id: int) -> None:
        if not self.settings.rate_limit_enabled:
            return
        if self._local_fallback_active[user_id] > 0:
            self._local_fallback_active[user_id] -= 1
            async with self._lock:
                self._active[user_id] = max(0, self._active[user_id] - 1)
            return
        if self._redis:
            try:
                await self._redis.decr(f"{self.settings.app_env}:agent:active:{user_id}")
                return
            except RedisError:
                logger.warning("Redis rate limiter release failed", exc_info=True)
        async with self._lock:
            self._active[user_id] = max(0, self._active[user_id] - 1)

    async def close(self) -> None:
        if self._redis:
            try:
                await self._redis.aclose()
            except RedisError:
                logger.debug("Redis limiter close failed", exc_info=True)

    async def _acquire_redis(self, user_id: int) -> None:
        prefix = f"{self.settings.app_env}:agent"
        minute_key = f"{prefix}:requests:{user_id}:{int(time.time() // 60)}"
        day_key = f"{prefix}:messages:{user_id}:{int(time.time() // 86400)}"
        active_key = f"{prefix}:active:{user_id}"
        pipe = self._redis.pipeline(transaction=True)
        pipe.incr(minute_key)
        pipe.expire(minute_key, 61)
        pipe.incr(day_key)
        pipe.expire(day_key, 86401)
        pipe.incr(active_key)
        pipe.expire(active_key, 3600)
        minute_count, _, day_count, _, active_count, _ = await pipe.execute()
        if minute_count > self.settings.requests_per_minute or day_count > self.settings.messages_per_day or active_count > self.settings.concurrent_streams:
            await self._redis.decr(active_key)
            if minute_count > self.settings.requests_per_minute:
                await self._redis.decr(minute_key)
            if day_count > self.settings.messages_per_day:
                await self._redis.decr(day_key)
            if active_count > self.settings.concurrent_streams:
                raise HTTPException(status_code=429, detail="同时进行的对话过多")
            if minute_count > self.settings.requests_per_minute:
                raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试")
            raise HTTPException(status_code=429, detail="今日对话次数已达上限")
