from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.model import ModelClient
from app.agent.tools import ToolRegistry
from app.clients.business import BusinessClient
from app.config import Settings
from app.graph.agent import LangGraphAgent
from app.llm.langchain_adapter import ExistingModelChatAdapter
from app.rag.embedding import EmbeddingService
from app.rag.qdrant_store import QdrantStore
from app.rag.rerank import RerankService
from app.rag.service import KnowledgeService
from app.security.identity import Identity


class FakeModelClient(ModelClient):
    @property
    def enabled(self) -> bool:
        return True

    async def complete(self, messages, tools):
        if any(item.get("role") == "tool" for item in messages):
            return {"message": {"content": "工具执行完成"}, "usage": {"prompt_tokens": 3, "completion_tokens": 2}, "model": "fake"}
        return {
            "message": {"content": None, "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "get_my_lessons", "arguments": "{}"}}]},
            "usage": {},
            "model": "fake",
        }

    async def stream(self, messages):
        yield "a"
        yield "b"


@pytest.mark.asyncio
async def test_existing_model_adapter_converts_all_message_roles_and_tool_calls():
    settings = Settings(ai_enabled=True, ai_api_key="test")
    client = FakeModelClient(settings)
    adapter = ExistingModelChatAdapter(client)
    converted = adapter._to_openai_messages([
        SystemMessage(content="system"),
        HumanMessage(content="human"),
        AIMessage(content="", tool_calls=[{"id": "call-1", "name": "get_my_lessons", "args": {}, "type": "tool_call"}]),
        ToolMessage(content="{}", tool_call_id="call-1"),
    ])
    assert [item["role"] for item in converted] == ["system", "user", "assistant", "tool"]
    assert json.loads(converted[2]["tool_calls"][0]["function"]["arguments"]) == {}


@pytest.mark.asyncio
async def test_single_agent_langgraph_executes_tool_and_observer_loop():
    settings = Settings(ai_enabled=True, ai_api_key="test", mock_business_mode=True)
    business = BusinessClient(settings)
    embeddings = EmbeddingService(settings)
    knowledge = KnowledgeService(settings, QdrantStore(settings, embeddings), embeddings, RerankService(settings))
    graph = LangGraphAgent(settings, FakeModelClient(settings), ToolRegistry(business, knowledge))
    events = []
    async for item in graph.astream(Identity(10, None, "request-1"), "conversation-1", "查询我的课表", {}, []):
        events.append(item)
    assert [item["name"] for item in events] == ["reasoning_status", "tool_started", "tool_completed", "content_delta", "completed"]
    assert events[-1]["data"]["inputTokens"] == 3
    await business.close()


def test_langchain_tools_use_closed_pydantic_schemas():
    registry = ToolRegistry(object(), object())
    tools = registry.langchain_tools(object())
    assert len(tools) == 10
    assert tools[1].args_schema.model_config["extra"] == "forbid"
