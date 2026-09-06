from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import event
from app.api.schemas import ChatRequest, context_dict
from app.graph.state import AgentEventModel
from app.observability.metrics import ACTIVE_STREAMS
from app.persistence.db import SessionFactory, get_session
from app.security.identity import Identity, get_identity
from app.services.chat import ChatService
from app.services.conversations import get_owned_conversation

router = APIRouter(prefix="/api/v1/conversations", tags=["chat"])
logger = logging.getLogger(__name__)


def _ws_event(event_type: str, data: dict[str, object], *, event_id: str | None = None, request_id: str | None = None, conversation_id: str | None = None) -> dict[str, object]:
    validated = AgentEventModel(name=event_type, data=data)
    result: dict[str, object] = {"type": validated.name, "data": validated.data, "timestamp": int(time.time() * 1000)}
    if event_id:
        result["eventId"] = event_id
    if request_id:
        result["requestId"] = request_id
    if conversation_id:
        result["conversationId"] = conversation_id
    return result


@router.post("/{conversation_id}/messages:ws-ticket")
async def websocket_ticket(
    conversation_id: str,
    request: Request,
    identity: Identity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    try:
        await get_owned_conversation(session, identity, conversation_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    ticket = secrets.token_urlsafe(32)
    ticket_store = getattr(request.app.state, "ticket_store", None)
    if ticket_store:
        await ticket_store.issue(ticket, identity.user_id, conversation_id, 30)
    else:
        tickets = getattr(request.app.state, "ws_tickets", None)
        if tickets is None:
            tickets = {}
            request.app.state.ws_tickets = tickets
        tickets[ticket] = {"userId": identity.user_id, "conversationId": conversation_id, "expire": time.monotonic() + 30.0}
    return {"code": 200, "msg": "OK", "data": {"ticket": ticket, "expiresIn": 30}, "requestId": identity.request_id}


@router.post("/{conversation_id}/messages:stream")
async def stream_chat(
    conversation_id: str,
    request_body: ChatRequest,
    request: Request,
    identity: Identity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    try:
        await get_owned_conversation(session, identity, conversation_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    limiter = request.app.state.rate_limiter
    await limiter.acquire(identity.user_id)
    ACTIVE_STREAMS.inc()
    chat_service: ChatService = request.app.state.chat_service

    async def generate():
        sequence = 0
        try:
            event_store = getattr(request.app.state, "event_store", None)
            resume_from = request.headers.get("last-event-id") or request.query_params.get("resumeFrom")
            if event_store and resume_from:
                replayed_events = await event_store.replay(identity.user_id, conversation_id, resume_from)
                for replayed in replayed_events:
                    replay_type = str(replayed.get("type") or "message")
                    replay_data = replayed.get("data") if isinstance(replayed.get("data"), dict) else {}
                    yield event(replay_type, replay_data, str(replayed.get("eventId") or ""), request_id=identity.request_id, conversation_id=conversation_id)
                if any(str(item.get("type")) == "completed" for item in replayed_events):
                    return
            stream = chat_service.stream(session, identity, conversation_id, request_body.message, context_dict(request_body.context)).__aiter__()
            while True:
                next_item = asyncio.create_task(stream.__anext__())
                done, _ = await asyncio.wait({next_item}, timeout=15)
                if not done:
                    next_item.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await next_item
                    yield ": heartbeat\n\n"
                    continue
                try:
                    item = next_item.result()
                except StopAsyncIteration:
                    break
                sequence += 1
                event_id = str(sequence)
                if event_store:
                    event_id = await event_store.append(identity.user_id, conversation_id, None, {"type": item["name"], "data": item["data"]})
                yield event(item["name"], item["data"], event_id, request_id=identity.request_id, conversation_id=conversation_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Agent stream failed")
            await session.rollback()
            yield event("error", {"code": "AGENT_ERROR", "message": "AI 助教暂时不可用，请稍后重试", "retryable": True}, request_id=identity.request_id, conversation_id=conversation_id)
        finally:
            await limiter.release(identity.user_id)
            ACTIVE_STREAMS.dec()

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.websocket("/{conversation_id}/messages:ws")
async def websocket_chat(websocket: WebSocket, conversation_id: str):
    await websocket.accept()
    ACTIVE_STREAMS.inc()
    ticket_store = getattr(websocket.app.state, "ticket_store", None)
    tickets = getattr(websocket.app.state, "ws_tickets", {})
    limiter = getattr(websocket.app.state, "rate_limiter", None)
    try:
        handshake = await websocket.receive_json()
        if not isinstance(handshake, dict):
            await websocket.close(code=1008, reason="请求格式无效")
            return
        ticket = str(handshake.get("ticket") or "")
        record = await ticket_store.consume(ticket) if ticket_store else tickets.pop(ticket, None)
        if not record or record["conversationId"] != conversation_id or (record.get("expire", time.monotonic() + 1) <= time.monotonic()):
            await websocket.close(code=4401, reason="WebSocket ticket 无效或已过期")
            return
        user_id = int(record["userId"])
        event_store = getattr(websocket.app.state, "event_store", None)
        service: ChatService = websocket.app.state.chat_service
        session_factory = getattr(websocket.app.state, "test_session_factory", SessionFactory)
        async with session_factory() as session:
            async def stream_one(payload: dict[str, object]) -> None:
                message = str(payload.get("message") or "").strip()
                request_id = str(payload.get("requestId") or websocket.headers.get("requestid") or secrets.token_hex(12))
                identity = Identity(user_id, None, request_id)
                if not message or len(message) > 4000:
                    await websocket.send_json({"type": "error", "data": {"code": 422, "message": "问题长度必须为 1 到 4000 个字符"}, "requestId": request_id, "conversationId": conversation_id, "timestamp": int(time.time() * 1000)})
                    return
                try:
                    await get_owned_conversation(session, identity, conversation_id)
                except LookupError:
                    await websocket.close(code=4404, reason="会话不存在")
                    return
                if limiter:
                    await limiter.acquire(user_id)
                try:
                    resume_from = str(payload.get("resumeFrom") or "")
                    if event_store and resume_from:
                        replayed_events = await event_store.replay(user_id, conversation_id, resume_from)
                        for replayed in replayed_events:
                            replay_type = str(replayed.get("type") or "message")
                            replay_data = replayed.get("data") if isinstance(replayed.get("data"), dict) else {}
                            await websocket.send_json(_ws_event(replay_type, replay_data, event_id=str(replayed.get("eventId") or ""), request_id=request_id, conversation_id=conversation_id))
                        if any(str(item.get("type")) == "completed" for item in replayed_events):
                            return
                    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
                    stream = service.stream(session, identity, conversation_id, message, context).__aiter__()
                    sequence = 0
                    while True:
                        next_item = asyncio.create_task(stream.__anext__())
                        done, _ = await asyncio.wait({next_item}, timeout=15)
                        if not done:
                            next_item.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await next_item
                            await websocket.send_json({"type": "heartbeat", "data": {"timestamp": int(time.time() * 1000)}, "requestId": request_id, "conversationId": conversation_id, "timestamp": int(time.time() * 1000)})
                            continue
                        try:
                            item = next_item.result()
                        except StopAsyncIteration:
                            break
                        sequence += 1
                        event_id = str(sequence)
                        if event_store:
                            event_id = await event_store.append(user_id, conversation_id, None, {"type": item["name"], "data": item["data"]})
                        await websocket.send_json(_ws_event(item["name"], item["data"], event_id=event_id, request_id=request_id, conversation_id=conversation_id))
                finally:
                    if limiter:
                        await limiter.release(user_id)

            # The ticket may be sent separately from the first business
            # message. Once authenticated, keep the socket open for multiple
            # sequential turns using the same event protocol as SSE.
            if handshake.get("message"):
                await stream_one(handshake)
            while True:
                payload = await websocket.receive_json()
                if not isinstance(payload, dict):
                    await websocket.send_json({"type": "error", "data": {"code": 422, "message": "请求格式无效"}, "conversationId": conversation_id, "timestamp": int(time.time() * 1000)})
                    continue
                await stream_one(payload)
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("WebSocket Agent stream failed")
        try:
            await websocket.send_json({"type": "error", "data": {"code": "AGENT_ERROR", "message": "AI 助教暂时不可用，请稍后重试", "retryable": True}})
        except Exception:
            return
    finally:
        ACTIVE_STREAMS.dec()
