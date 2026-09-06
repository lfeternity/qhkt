from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import PromptVersion


async def get_active_prompt(session: AsyncSession, prompt_key: str, fallback: str, fallback_version: str = "default") -> tuple[str, str]:
    result = await session.execute(
        select(PromptVersion)
        .where(PromptVersion.prompt_key == prompt_key, PromptVersion.status == "ACTIVE")
        .order_by(PromptVersion.update_time.desc())
        .limit(1)
    )
    prompt = result.scalar_one_or_none()
    return (prompt.content, prompt.version) if prompt else (fallback, fallback_version)
