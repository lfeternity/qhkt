from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.language_models.chat_models import (
    AsyncCallbackManagerForLLMRun,
    BaseChatModel,
)
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict, PrivateAttr

from app.agent.model import ModelClient


class ExistingModelChatAdapter(BaseChatModel):
    """Expose the unchanged OpenAI-compatible client as a LangChain chat model."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    model_name: str = ""
    _client: ModelClient = PrivateAttr()

    def __init__(self, client: ModelClient, **kwargs: Any) -> None:
        super().__init__(model_name=client.settings.ai_chat_model, **kwargs)
        self._client = client

    @property
    def _llm_type(self) -> str:
        return "qhkt-existing-model-client"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model_name, "base_url": self._client.settings.ai_base_url}

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Any | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, BaseMessage]:
        schemas = [convert_to_openai_tool(tool) for tool in tools]
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        return self.bind(tools=schemas, **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            response = asyncio.run(self._complete(messages, kwargs))
        else:
            raise RuntimeError("同步模型调用不能运行在事件循环中，请使用 ainvoke")
        return self._chat_result(response)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._chat_result(await self._complete(messages, kwargs))

    async def _complete(self, messages: list[BaseMessage], kwargs: dict[str, Any]) -> dict[str, Any]:
        tools = kwargs.get("tools") or []
        return await self._client.complete(self._to_openai_messages(messages), tools)

    def _chat_result(self, response: dict[str, Any]) -> ChatResult:
        raw = response.get("message") or {}
        content = raw.get("content") or ""
        tool_calls: list[dict[str, Any]] = []
        for call in raw.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") or {}
            arguments = function.get("arguments") or "{}"
            if isinstance(arguments, dict):
                parsed_arguments = arguments
            else:
                try:
                    parsed_arguments = json.loads(str(arguments))
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed_arguments = {}
            tool_calls.append({
                "name": str(function.get("name") or ""),
                "args": parsed_arguments if isinstance(parsed_arguments, dict) else {},
                "id": str(call.get("id") or ""),
                "type": "tool_call",
            })
        message = AIMessage(
            content=str(content),
            tool_calls=tool_calls,
            response_metadata={"model": response.get("model"), "usage": response.get("usage") or {}},
        )
        return ChatResult(generations=[ChatGeneration(message=message)], llm_output=response.get("usage") or {})

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        async for delta in self._client.stream(self._to_openai_messages(messages)):
            chunk = AIMessageChunk(content=delta)
            if run_manager:
                await run_manager.on_llm_new_token(delta)
            yield ChatGenerationChunk(message=chunk)

    def _to_openai_messages(self, messages: list[BaseMessage]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, SystemMessage):
                converted.append({"role": "system", "content": self._content(message.content)})
            elif isinstance(message, HumanMessage):
                converted.append({"role": "user", "content": self._content(message.content)})
            elif isinstance(message, ToolMessage):
                converted.append({
                    "role": "tool",
                    "tool_call_id": str(message.tool_call_id),
                    "content": self._content(message.content),
                })
            elif isinstance(message, AIMessage):
                item: dict[str, Any] = {"role": "assistant", "content": self._content(message.content)}
                if message.tool_calls:
                    item["tool_calls"] = [
                        {
                            "id": str(call.get("id") or ""),
                            "type": "function",
                            "function": {
                                "name": str(call.get("name") or ""),
                                "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False),
                            },
                        }
                        for call in message.tool_calls
                    ]
                converted.append(item)
            else:
                converted.append({"role": "user", "content": self._content(message.content)})
        return converted

    def _content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False, default=str)
