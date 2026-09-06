from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.main import app
from app.persistence.models import PendingAction, now_utc


def auth(user_id: int) -> dict[str, str]:
    return {"user-info": str(user_id), "requestId": f"test-{user_id}"}


def parse_events(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines and "data" in lines:
            events.append((lines["event"], json.loads(lines["data"])["data"]))
    return events


@pytest.mark.asyncio
async def test_authentication_and_conversation_ownership(test_env):
    response = await test_env.get("/api/v1/conversations")
    assert response.status_code == 401
    assert response.json()["code"] == 401
    assert response.json()["requestId"]

    created = await test_env.post("/api/v1/conversations", headers=auth(10), json={"title": "我的对话"})
    assert created.status_code == 200
    conversation_id = created.json()["data"]["id"]
    other_user = await test_env.get(f"/api/v1/conversations/{conversation_id}/messages", headers=auth(11))
    assert other_user.status_code == 404
    owner = await test_env.get(f"/api/v1/conversations/{conversation_id}/messages", headers=auth(10))
    assert owner.status_code == 200


@pytest.mark.asyncio
async def test_sse_persists_messages_and_returns_tool_events(test_env):
    created = await test_env.post("/api/v1/conversations", headers=auth(10), json={})
    conversation_id = created.json()["data"]["id"]
    response = await test_env.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers=auth(10),
        json={"message": "请告诉我课表"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_events(response.text)
    names = [name for name, _ in events]
    assert names[0] == "metadata"
    assert "tool_started" in names
    assert "content_delta" in names
    assert names[-1] == "completed"
    messages = await test_env.get(f"/api/v1/conversations/{conversation_id}/messages", headers=auth(10))
    assert len(messages.json()["data"]) == 2
    assert messages.json()["data"][1]["content"]


@pytest.mark.asyncio
async def test_rag_acl_citations_and_practice_answer_filter(test_env):
    document = await test_env.post(
        "/api/v1/admin/knowledge/documents",
        headers=auth(1),
        json={"courseId": 9, "title": "检索资料", "content": "向量检索需要先进行课程权限校验。"},
    )
    assert document.status_code == 200
    document_id = document.json()["data"]["id"]
    published = await test_env.post(f"/api/v1/admin/knowledge/documents/{document_id}:publish", headers=auth(1))
    assert published.status_code == 200
    conversation = await test_env.post("/api/v1/conversations", headers=auth(10), json={})
    conversation_id = conversation.json()["data"]["id"]
    rag = await test_env.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers=auth(10),
        json={"message": "什么是向量检索？", "context": {"courseId": 9}},
    )
    events = parse_events(rag.text)
    assert any(name == "citation" and data["courseId"] == 9 for name, data in events)

    practice = await test_env.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers=auth(10),
        json={"message": "查看练习", "context": {"courseId": 9, "sectionId": 111}},
    )
    assert "answer" not in practice.text.lower()
    assert "analysis" not in practice.text.lower()


@pytest.mark.asyncio
async def test_prepare_confirm_idempotency_cancel_and_expiry(test_env):
    conversation = await test_env.post("/api/v1/conversations", headers=auth(10), json={})
    conversation_id = conversation.json()["data"]["id"]
    response = await test_env.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers=auth(10),
        json={"message": "帮我制定学习计划", "context": {"courseId": 9, "chapterId": 11, "sectionId": 111}},
    )
    events = parse_events(response.text)
    action_id = next(data["actionId"] for name, data in events if name == "tool_confirmation_required")
    first = await test_env.post(f"/api/v1/actions/{action_id}/confirm", headers=auth(10))
    second = await test_env.post(f"/api/v1/actions/{action_id}/confirm", headers=auth(10))
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["status"] == second.json()["data"]["status"] == "CONFIRMED"

    cancelled_conversation = await test_env.post("/api/v1/conversations", headers=auth(10), json={})
    cancelled_conversation_id = cancelled_conversation.json()["data"]["id"]
    cancelled = await test_env.post(
        f"/api/v1/conversations/{cancelled_conversation_id}/messages:stream",
        headers=auth(10),
        json={"message": "帮我制定学习计划", "context": {"courseId": 9, "chapterId": 11, "sectionId": 111}},
    )
    cancelled_id = next(data["actionId"] for name, data in parse_events(cancelled.text) if name == "tool_confirmation_required")
    cancel_response = await test_env.post(f"/api/v1/actions/{cancelled_id}/cancel", headers=auth(10))
    assert cancel_response.json()["data"]["status"] == "CANCELLED"

    expired_conversation = await test_env.post("/api/v1/conversations", headers=auth(10), json={})
    expired_conversation_id = expired_conversation.json()["data"]["id"]
    expired = await test_env.post(
        f"/api/v1/conversations/{expired_conversation_id}/messages:stream",
        headers=auth(10),
        json={"message": "帮我制定学习计划", "context": {"courseId": 9, "chapterId": 11, "sectionId": 111}},
    )
    expired_id = next(data["actionId"] for name, data in parse_events(expired.text) if name == "tool_confirmation_required")
    async with app.state.test_session_factory() as session:
        action = await session.get(PendingAction, expired_id)
        action.expire_time = now_utc() - timedelta(seconds=1)
        await session.commit()
    expired_response = await test_env.post(f"/api/v1/actions/{expired_id}/confirm", headers=auth(10))
    assert expired_response.status_code == 409
    async with app.state.test_session_factory() as session:
        action = await session.get(PendingAction, expired_id)
        assert action.status == "EXPIRED"


@pytest.mark.asyncio
async def test_transcript_upload_and_prompt_activation(test_env):
    subtitle = b"1\n00:00:01,000 --> 00:00:03,000\nRAG needs ACL\n"
    uploaded = await test_env.post(
        "/api/v1/admin/knowledge/transcripts",
        headers=auth(1),
        files={"file": ("lesson.srt", subtitle, "text/plain")},
        data={"courseId": "9", "title": "Lesson transcript"},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["data"]["document"]["source_type"] == "TRANSCRIPT"
    assert uploaded.json()["data"]["job"]["status"] == "PENDING"

    prompt = await test_env.post(
        "/api/v1/admin/prompts",
        headers=auth(1),
        json={"promptKey": "learning-assistant", "version": "v-test", "content": "Answer with evidence."},
    )
    assert prompt.status_code == 200
    prompt_id = prompt.json()["data"]["id"]
    activated = await test_env.post(f"/api/v1/admin/prompts/{prompt_id}:publish", headers=auth(1))
    assert activated.status_code == 200

    conversation = await test_env.post("/api/v1/conversations", headers=auth(10), json={})
    stream = await test_env.post(
        f"/api/v1/conversations/{conversation.json()['data']['id']}/messages:stream",
        headers=auth(10),
        json={"message": "你好"},
    )
    metadata = next(data for name, data in parse_events(stream.text) if name == "metadata")
    assert metadata["promptVersion"] == "v-test"
