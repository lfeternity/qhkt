from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import Settings


class ModelError(RuntimeError):
    pass


class ModelClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.timeout = httpx.Timeout(settings.ai_timeout_seconds)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.ai_enabled and self.settings.ai_api_key)

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.enabled:
            raise ModelError("模型未启用")
        payload: dict[str, Any] = {
            "model": self.settings.ai_chat_model,
            "messages": messages,
            "temperature": self.settings.ai_temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        for attempt in range(self.settings.ai_max_retries + 1):
            try:
                async with httpx.AsyncClient(base_url=self.settings.ai_base_url.rstrip("/"), timeout=self.timeout) as client:
                    response = await client.post("chat/completions", json=payload, headers={"Authorization": f"Bearer {self.settings.ai_api_key}"})
                    response.raise_for_status()
                    body = response.json()
                    if not isinstance(body, dict):
                        raise TypeError("invalid model response")
                    choices = body.get("choices") or []
                    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                        raise TypeError("invalid model choices")
                    choice = choices[0]
                    message = choice.get("message") or {}
                    return {"message": message, "usage": body.get("usage") or {}, "model": body.get("model") or self.settings.ai_chat_model}
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                if attempt >= self.settings.ai_max_retries or not self._retryable(error):
                    raise ModelError("AI 模型暂时不可用") from error
                await asyncio.sleep(0.2 * (attempt + 1))
        raise ModelError("AI 模型暂时不可用")

    async def stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        if not self.enabled:
            raise ModelError("模型未启用")
        payload = {"model": self.settings.ai_chat_model, "messages": messages, "temperature": self.settings.ai_temperature, "stream": True}
        try:
            async with (
                httpx.AsyncClient(base_url=self.settings.ai_base_url.rstrip("/"), timeout=self.timeout) as client,
                client.stream("POST", "chat/completions", json=payload, headers={"Authorization": f"Bearer {self.settings.ai_api_key}"}) as response,
            ):
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        choices = data.get("choices") if isinstance(data, dict) else None
                        delta = ((choices or [{}])[0].get("delta") or {}).get("content") if isinstance((choices or [{}])[0], dict) else None
                        if delta:
                            yield str(delta)
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
            raise ModelError("AI 模型暂时不可用") from error

    def _retryable(self, error: Exception) -> bool:
        return isinstance(error, (httpx.TimeoutException, httpx.NetworkError)) or (
            isinstance(error, httpx.HTTPStatusError) and error.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
        )
