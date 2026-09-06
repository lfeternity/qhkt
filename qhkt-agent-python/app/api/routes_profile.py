from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import ok
from app.api.schemas import ProfileRequest
from app.persistence.db import get_session
from app.persistence.models import UserProfile, model_to_dict
from app.security.identity import Identity, get_identity
from app.services.memory import upsert_memory_fact

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


@router.get("")
async def get_profile(identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    value = await session.get(UserProfile, identity.user_id)
    return ok(model_to_dict(value) if value else None, identity)


@router.put("")
async def save_profile(payload: ProfileRequest, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    value = await session.get(UserProfile, identity.user_id)
    if not value:
        value = UserProfile(user_id=identity.user_id)
        session.add(value)
    value.learning_goal = payload.learningGoal
    value.preferred_style = payload.preferredStyle
    value.weekly_hours = payload.weeklyHours
    value.consented = payload.consented
    if payload.consented:
        if payload.learningGoal:
            await upsert_memory_fact(session, identity.user_id, "learning_goal", payload.learningGoal)
        if payload.preferredStyle:
            await upsert_memory_fact(session, identity.user_id, "preferred_style", payload.preferredStyle)
        if payload.weeklyHours is not None:
            await upsert_memory_fact(session, identity.user_id, "weekly_hours", str(payload.weeklyHours))
    else:
        from app.services.memory import delete_user_memory

        await delete_user_memory(session, identity.user_id)
    await session.commit()
    return ok(model_to_dict(value), identity)


@router.delete("")
async def delete_profile(request: Request, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    value = await session.get(UserProfile, identity.user_id)
    if value:
        await session.delete(value)
    from app.services.memory import delete_user_memory

    await delete_user_memory(session, identity.user_id)
    await session.commit()
    memory = getattr(request.app.state, "short_term_memory", None)
    if memory:
        await memory.delete_user(identity.user_id)
    return ok(None, identity)
