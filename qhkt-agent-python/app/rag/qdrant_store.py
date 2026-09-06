from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.persistence.models import KnowledgeChunk
from app.rag.embedding import EmbeddingService


class QdrantStore:
    def __init__(self, settings: Settings, embeddings: EmbeddingService) -> None:
        self.settings = settings
        self.embeddings = embeddings

    async def ensure_collection(self) -> None:
        if not self.settings.qdrant_enabled:
            return
        url = f"{self.settings.qdrant_url.rstrip('/')}/collections/{self.settings.qdrant_collection}"
        headers = self._headers()
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                try:
                    vectors = response.json().get("result", {}).get("config", {}).get("params", {}).get("vectors", {})
                    size = vectors.get("size") if isinstance(vectors, dict) else None
                    if size is not None and int(size) != self.settings.embedding_dimension:
                        raise RuntimeError("Qdrant collection dimension does not match embedding dimension")
                except (ValueError, TypeError, AttributeError) as error:
                    raise RuntimeError("Qdrant collection metadata is invalid") from error
            else:
                body = {"vectors": {"size": self.settings.embedding_dimension, "distance": "Cosine"}}
                created = await client.put(url, json=body, headers=headers)
                created.raise_for_status()
            for field_name in ("course_id", "chapter_id", "section_id", "document_id"):
                index_response = await client.put(
                    f"{url}/index",
                    json={"field_name": field_name, "field_schema": "keyword" if field_name == "document_id" else "integer"},
                    headers=headers,
                )
                if index_response.status_code not in {200, 201, 409}:
                    index_response.raise_for_status()

    async def upsert(self, chunks: list[KnowledgeChunk]) -> None:
        if not self.settings.qdrant_enabled or not chunks:
            return
        await self.ensure_collection()
        points = []
        for chunk in chunks:
            points.append({
                "id": chunk.id,
                "vector": await self.embeddings.embed_async(chunk.content),
                "payload": {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "course_id": chunk.course_id,
                    "chapter_id": chunk.chapter_id,
                    "section_id": chunk.section_id,
                    "title": chunk.title,
                    "source_type": chunk.source_type,
                    "source_id": chunk.source_id,
                    "content": chunk.content,
                    "start_moment": chunk.start_moment,
                    "end_moment": chunk.end_moment,
                },
            })
        url = f"{self.settings.qdrant_url.rstrip('/')}/collections/{self.settings.qdrant_collection}/points"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.put(url, json={"points": points}, headers=self._headers())
            response.raise_for_status()

    async def search(self, query: str, course_id: int, section_id: int | None, limit: int = 8) -> list[dict[str, Any]]:
        if not self.settings.qdrant_enabled:
            return []
        try:
            await self.ensure_collection()
            must: list[dict[str, Any]] = [{"key": "course_id", "match": {"value": course_id}}]
            # Section ACL is applied against relational rows after vector recall. This also
            # keeps course-level documents visible from a section page without null filters.
            body = {
                "vector": await self.embeddings.embed_async(query),
                "limit": limit,
                "with_payload": True,
                "filter": {"must": must},
            }
            url = f"{self.settings.qdrant_url.rstrip('/')}/collections/{self.settings.qdrant_collection}/points/search"
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(url, json=body, headers=self._headers())
                response.raise_for_status()
                result = response.json().get("result", [])
                return [{**(item.get("payload") or {}), "score": item.get("score", 0)} for item in result]
        except (httpx.HTTPError, ValueError, RuntimeError):
            return []

    async def delete_course(self, course_id: int) -> None:
        if not self.settings.qdrant_enabled:
            return
        url = f"{self.settings.qdrant_url.rstrip('/')}/collections/{self.settings.qdrant_collection}/points/delete"
        body = {"filter": {"must": [{"key": "course_id", "match": {"value": course_id}}]}}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, json=body, headers=self._headers())
                response.raise_for_status()
        except (httpx.HTTPError, ValueError):
            # Database ACL remains authoritative when vector cleanup is unavailable.
            return

    def _headers(self) -> dict[str, str]:
        return {"api-key": self.settings.qdrant_api_key} if self.settings.qdrant_api_key else {}
