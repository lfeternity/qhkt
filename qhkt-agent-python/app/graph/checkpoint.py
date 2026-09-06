from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from app.config import Settings


async def build_checkpointer(settings: Settings) -> tuple[Any, bool]:
    """Create a persistent Redis saver, or an explicit development saver.

    The boolean says whether persistence is required. Production callers must
    fail startup when Redis cannot be configured instead of silently using
    process-local state.
    """
    if settings.redis_url:
        try:
            from langgraph.checkpoint.redis import AsyncRedisSaver

            saver = AsyncRedisSaver(
                settings.redis_url,
                ttl={"default_ttl": max(1, settings.graph_checkpoint_ttl_seconds // 60), "refresh_on_read": True},
            )
            await saver.asetup()
            return saver, True
        except Exception:
            if settings.production_mode:
                raise
    if settings.production_mode:
        raise RuntimeError("生产环境必须配置可用的 Redis LangGraph checkpoint")
    return MemorySaver(), False
