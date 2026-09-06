from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import ok
from app.clients.business import BusinessUnavailable
from app.persistence.db import get_session
from app.security.identity import Identity, get_identity
from app.services.actions import cancel_action, confirm_action

router = APIRouter(prefix="/api/v1/actions", tags=["actions"])


@router.post("/{action_id}/confirm")
async def confirm(action_id: str, request: Request, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    try:
        value = await confirm_action(session, identity, action_id, request.app.state.business)
        return ok(value, identity)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except BusinessUnavailable as error:
        await session.rollback()
        raise HTTPException(status_code=503, detail="业务服务暂时不可用，请稍后重试") from error
    except RuntimeError as error:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/{action_id}/cancel")
async def cancel(action_id: str, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    try:
        return ok(await cancel_action(session, identity, action_id), identity)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
