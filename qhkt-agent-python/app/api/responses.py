from __future__ import annotations

from typing import Any

from app.graph.state import AgentEventModel
from app.security.identity import Identity


def ok(data: Any = None, identity: Identity | None = None) -> dict[str, Any]:
    return {"code": 200, "msg": "OK", "data": data, "requestId": identity.request_id if identity else None}


def error(code: int, message: str, identity: Identity | None = None) -> dict[str, Any]:
    return {"code": code, "msg": message, "data": None, "requestId": identity.request_id if identity else None}


def event(name: str, data: dict[str, Any], event_id: str | None = None, *, request_id: str | None = None, conversation_id: str | None = None) -> str:
    import json

    validated = AgentEventModel(name=name, data=data)
    identifier = f"id: {event_id}\n" if event_id else ""
    envelope = {"type": validated.name, "data": validated.data}
    if event_id:
        envelope["eventId"] = event_id
    if request_id:
        envelope["requestId"] = request_id
    if conversation_id:
        envelope["conversationId"] = conversation_id
    envelope["timestamp"] = int(__import__("time").time() * 1000)
    return f"{identifier}event: {name}\ndata: {json.dumps(envelope, ensure_ascii=False)}\n\n"
