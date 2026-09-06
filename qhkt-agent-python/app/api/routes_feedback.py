from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import ok
from app.api.schemas import FeedbackRequest
from app.persistence.db import get_session
from app.security.identity import Identity, get_identity
from app.services.conversations import save_feedback

router = APIRouter(prefix="/api/v1/messages", tags=["feedback"])


@router.post("/{message_id}/feedback")
async def feedback(message_id: str, request: FeedbackRequest, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    rating = request.rating.strip().upper()
    if rating not in {"UP", "DOWN"}:
        raise HTTPException(status_code=400, detail="反馈类型只能是 UP 或 DOWN")
    try:
        await save_feedback(session, identity, message_id, rating, request.reason, request.comment)
        return ok(None, identity)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
