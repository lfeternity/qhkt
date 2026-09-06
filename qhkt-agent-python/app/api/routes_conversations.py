from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import ok
from app.api.schemas import CreateConversationRequest
from app.config import get_settings
from app.persistence.db import get_session
from app.security.identity import Identity, get_identity
from app.services.conversations import (
    create_conversation,
    delete_conversation,
    list_conversations,
    list_messages,
)

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


@router.post("")
async def create(request: CreateConversationRequest, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    return ok(await create_conversation(session, identity, request.title, request.scene, get_settings()), identity)


@router.get("")
async def list_all(identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    return ok(await list_conversations(session, identity), identity)


@router.get("/{conversation_id}/messages")
async def messages(conversation_id: str, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    try:
        return ok(await list_messages(session, identity, conversation_id), identity)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/{conversation_id}")
async def remove(conversation_id: str, request: Request, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    try:
        await delete_conversation(session, identity, conversation_id)
        memory = getattr(request.app.state, "short_term_memory", None)
        if memory:
            await memory.delete(identity.user_id, conversation_id)
        events = getattr(request.app.state, "event_store", None)
        if events:
            await events.delete(identity.user_id, conversation_id)
        return ok(None, identity)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
