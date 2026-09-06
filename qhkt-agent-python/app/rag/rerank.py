from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import httpx

from app.config import Settings

if TYPE_CHECKING:
    from app.rag.service import SearchHit


class RerankService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def rerank(self, query: str, hits: list[SearchHit]) -> list[SearchHit]:
        if not self.settings.rerank_enabled or not self.settings.rerank_base_url or not hits:
            return hits
        payload = {
            "model": self.settings.rerank_model,
            "query": query,
            "documents": [hit.content for hit in hits],
            "top_n": min(self.settings.rerank_top_n, len(hits)),
        }
        headers = {"Authorization": f"Bearer {self.settings.rerank_api_key}"} if self.settings.rerank_api_key else {}
        try:
            async with httpx.AsyncClient(timeout=self.settings.rerank_timeout_seconds) as client:
                response = await client.post(f"{self.settings.rerank_base_url.rstrip('/')}/rerank", json=payload, headers=headers)
                response.raise_for_status()
                items = response.json().get("results", [])
            reranked: list[SearchHit] = []
            seen: set[int] = set()
            for item in items:
                index = int(item.get("index", -1))
                if 0 <= index < len(hits):
                    if index in seen:
                        continue
                    seen.add(index)
                    reranked.append(replace(hits[index], score=float(item.get("relevance_score", hits[index].score))))
            reranked.extend(hit for index, hit in enumerate(hits) if index not in seen)
            return reranked or hits
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return hits
