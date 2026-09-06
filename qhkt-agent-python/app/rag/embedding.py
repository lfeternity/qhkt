from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from typing import Any

import httpx

from app.config import Settings


class EmbeddingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def embed(self, text: str) -> list[float]:
        """Synchronous local fixture embedding; production must use ``embed_async``."""
        if self.settings.production_mode and self.settings.embedding_provider.upper() == "LOCAL_HASH":
            raise RuntimeError("生产环境禁止使用 LOCAL_HASH embedding")
        dimension = self.settings.embedding_dimension
        vector = [0.0] * dimension
        encoded = text.encode("utf-8")
        if not encoded:
            return vector
        for index, token in enumerate(self._tokens(text)):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            slot = int.from_bytes(digest[:4], "big") % dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[slot] += sign / math.sqrt(index + 1)
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    async def embed_async(self, text: str) -> list[float]:
        provider = self.settings.embedding_provider.upper()
        if provider in {"LOCAL_HASH", "TEST"}:
            return self.embed(text)
        if provider not in {"HTTP", "OPENAI", "OPENAI_COMPATIBLE", "BGE"}:
            raise ValueError(f"不支持的 embedding provider: {provider}")
        if not self.settings.embedding_base_url or not self.settings.embedding_api_key:
            raise RuntimeError("embedding provider 缺少 base URL 或 API key")
        payload = {"model": self.settings.embedding_model, "input": text}
        headers = {"Authorization": f"Bearer {self.settings.embedding_api_key}"}
        async with httpx.AsyncClient(base_url=self.settings.embedding_base_url.rstrip("/"), timeout=self.settings.embedding_timeout_seconds) as client:
            response = await client.post("embeddings", json=payload, headers=headers)
            response.raise_for_status()
            body: Any = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ValueError("embedding 响应格式无效")
        vector = data[0].get("embedding")
        if not isinstance(vector, list) or len(vector) != self.settings.embedding_dimension:
            raise ValueError("embedding 维度与配置不一致")
        return [float(value) for value in vector]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_async(text) for text in texts]

    def _tokens(self, text: str) -> Iterable[str]:
        normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
        for word in normalized.split():
            yield word
            if any("\u4e00" <= char <= "\u9fff" for char in word):
                for index in range(len(word) - 1):
                    yield word[index : index + 2]
