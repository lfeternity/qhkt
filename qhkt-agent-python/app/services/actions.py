from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.business import BusinessClient
from app.persistence.models import PendingAction, now_utc
from app.security.identity import Identity


def _key(user_id: int, conversation_id: str, action_type: str, payload: dict[str, Any]) -> str:
    value = f"{user_id}:{conversation_id}:{action_type}:{json.dumps(payload, sort_keys=True, ensure_ascii=False)}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def action_dict(action: PendingAction) -> dict[str, Any]:
    return {"id": action.id, "actionType": action.action_type, "summary": action.result_message, "status": action.status, "expireTime": action.expire_time.isoformat() if action.expire_time else None}


async def prepare_action(session: AsyncSession, user_id: int, conversation_id: str, action_type: str, payload: dict[str, Any], summary: str) -> dict[str, Any]:
    key = _key(user_id, conversation_id, action_type, payload)
    existing = (await session.execute(select(PendingAction).where(PendingAction.idempotency_key == key))).scalar_one_or_none()
    if existing:
        return action_dict(existing)
    action = PendingAction(user_id=user_id, conversation_id=conversation_id, action_type=action_type, payload=json.dumps(payload, ensure_ascii=False), status="PENDING", expire_time=now_utc() + timedelta(minutes=10), idempotency_key=key, result_message=summary)
    session.add(action)
    await session.flush()
    return action_dict(action)


async def get_owned_action(session: AsyncSession, identity: Identity, action_id: str) -> PendingAction:
    result = await session.execute(
        select(PendingAction)
        .where(PendingAction.id == action_id, PendingAction.user_id == identity.user_id)
        .with_for_update()
    )
    action = result.scalar_one_or_none()
    if not action:
        raise LookupError("待确认操作不存在")
    return action


async def confirm_action(session: AsyncSession, identity: Identity, action_id: str, business: BusinessClient) -> dict[str, Any]:
    action = await get_owned_action(session, identity, action_id)
    if action.status == "CONFIRMED":
        return action_dict(action)
    if action.status == "EXECUTING":
        raise RuntimeError("该操作正在执行，请稍后查询")
    if action.status != "PENDING":
        raise RuntimeError("该操作已处理")
    if action.expire_time <= now_utc():
        action.status = "EXPIRED"
        await session.commit()
        raise RuntimeError("该确认操作已过期")
    claimed = await session.execute(
        update(PendingAction)
        .where(PendingAction.id == action.id, PendingAction.status == "PENDING", PendingAction.version == action.version)
        .values(status="EXECUTING", version=action.version + 1)
    )
    if claimed.rowcount != 1:
        await session.rollback()
        raise RuntimeError("该操作正在执行，请稍后查询")
    await session.commit()
    try:
        payload = json.loads(action.payload)
        if action.action_type == "CREATE_LEARNING_PLAN":
            await business.create_learning_plan(identity, payload, action.idempotency_key)
        elif action.action_type == "CREATE_NOTE":
            await business.create_note(identity, payload, action.idempotency_key)
        elif action.action_type == "CREATE_QUESTION":
            await business.create_question(identity, payload, action.idempotency_key)
        else:
            raise ValueError("不支持的操作类型")
    except Exception:
        action = await session.get(PendingAction, action.id)
        if action and action.status == "EXECUTING":
            action.status = "PENDING"
            action.version += 1
            await session.commit()
        raise
    action = await session.get(PendingAction, action.id)
    if not action:
        raise LookupError("待确认操作不存在")
    action.status = "CONFIRMED"
    action.result_message = "操作已执行"
    action.version += 1
    await session.commit()
    return action_dict(action)


async def cancel_action(session: AsyncSession, identity: Identity, action_id: str) -> dict[str, Any]:
    action = await get_owned_action(session, identity, action_id)
    if action.status == "PENDING":
        action.status = "CANCELLED"
        action.result_message = "操作已取消"
        await session.commit()
    return action_dict(action)
