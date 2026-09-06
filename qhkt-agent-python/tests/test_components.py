from __future__ import annotations

import httpx

from app.agent.tools import ToolRegistry
from app.clients.business import BusinessClient, strip_answers
from app.config import Settings
from app.persistence.models import Message
from app.rag.transcript import encode_segments, parse_subtitle
from app.services.memory import build_summary


def test_strip_answers_recursively_removes_answer_fields():
    value = {"question": "q", "answer": "A", "correctAnswer": "A", "analysis": "secret", "options": [{"analysis": "x", "label": "A"}]}
    assert strip_answers(value) == {"question": "q", "options": [{"label": "A"}]}


def test_subtitle_parser_preserves_timeline_and_rejects_bad_extension():
    content = "1\n00:00:01,000 --> 00:00:03,000\n第一句\n\n2\n00:00:04,000 --> 00:00:05,500\n第二句\n"
    segments = parse_subtitle("lesson.srt", content)
    assert [(item.start_moment, item.end_moment) for item in segments] == [(1, 3), (4, 6)]
    assert encode_segments(segments).startswith("[[1:3]] 第一句")

    try:
        parse_subtitle("lesson.pdf", "x")
    except ValueError as error:
        assert "SRT" in str(error)
    else:
        raise AssertionError("unsupported subtitle extension must fail")


def test_tool_schemas_are_closed_and_limit_page_size():
    # Registry construction only needs collaborators for schema inspection.
    registry = ToolRegistry(object(), object())
    schemas = {item["function"]["name"]: item for item in registry.schemas()}
    assert len(schemas) == 10
    assert schemas["get_my_lessons"]["function"]["parameters"]["additionalProperties"] is False
    assert schemas["get_my_lessons"]["function"]["parameters"]["properties"]["pageSize"]["maximum"] == 20


def test_memory_summary_is_bounded_and_excludes_empty_system_messages():
    messages = [
        Message(role="SYSTEM", content="secret prompt", user_id=1, conversation_id="c"),
        Message(role="USER", content="first question", user_id=1, conversation_id="c"),
        Message(role="ASSISTANT", content="answer", user_id=1, conversation_id="c"),
    ]
    summary = build_summary(messages, max_chars=20)
    assert summary is not None and len(summary) <= 20
    assert "secret prompt" not in summary


def test_business_client_accepts_empty_success_responses():
    client = BusinessClient(Settings())
    request = httpx.Request("POST", "http://service.test")
    assert client._parse(httpx.Response(204, request=request, content=b"")) is None
    assert client._parse(httpx.Response(200, request=request, content=b"")) is None
