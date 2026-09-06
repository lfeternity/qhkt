from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, PrivateAttr
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.persistence.models import KnowledgeChunk, KnowledgeDocument, now_utc
from app.rag.embedding import EmbeddingService
from app.rag.loaders import split_documents
from app.rag.qdrant_store import QdrantStore
from app.rag.rerank import RerankService
from app.rag.transcript import decode_segments
from app.security.identity import Identity


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    title: str
    content: str
    source_type: str
    source_id: str | None
    course_id: int | None
    chapter_id: int | None
    section_id: int | None
    start_moment: int | None
    end_moment: int | None
    score: float
    page_number: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunkId": self.chunk_id,
            "title": self.title,
            "content": self.content,
            "sourceType": self.source_type,
            "sourceId": self.source_id,
            "courseId": self.course_id,
            "chapterId": self.chapter_id,
            "sectionId": self.section_id,
            "startMoment": self.start_moment,
            "endMoment": self.end_moment,
            "page": self.page_number,
            "score": round(self.score, 6),
        }


class KnowledgeService:
    def __init__(self, settings: Settings, qdrant: QdrantStore, embeddings: EmbeddingService, rerank: RerankService | None = None) -> None:
        self.settings = settings
        self.qdrant = qdrant
        self.embeddings = embeddings
        self.rerank = rerank or RerankService(settings)

    async def create_document(self, session: AsyncSession, payload: dict[str, Any]) -> KnowledgeDocument:
        content = self._clean(str(payload.get("content") or ""))
        title = str(payload.get("title") or "").strip()
        source_type = str(payload.get("sourceType") or "COURSE").strip().upper()
        visibility = str(payload.get("visibility") or "ENROLLED").strip().upper()
        if not payload.get("courseId") or not title or not content:
            raise ValueError("知识文档的课程、标题和内容不能为空")
        if visibility not in {"PUBLIC", "ENROLLED"}:
            raise ValueError("知识文档可见性只能是 PUBLIC 或 ENROLLED")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        result = await session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.course_id == int(payload["courseId"]),
                KnowledgeDocument.source_type == source_type,
                KnowledgeDocument.source_id == payload.get("sourceId"),
                KnowledgeDocument.content_hash == digest,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        document = KnowledgeDocument(
            course_id=int(payload["courseId"]),
            chapter_id=payload.get("chapterId"),
            section_id=payload.get("sectionId"),
            source_type=source_type,
            source_id=str(payload.get("sourceId")) if payload.get("sourceId") is not None else None,
            title=title[:300],
            content=content,
            content_hash=digest,
            version=int(payload.get("version") or 1),
            status="DRAFT",
            visibility=visibility,
            source_url=payload.get("sourceUrl"),
            object_file_id=str(payload.get("objectFileId")) if payload.get("objectFileId") is not None else None,
            object_key=payload.get("objectKey"),
            mime_type=payload.get("mimeType"),
            file_size=payload.get("fileSize"),
            checksum=payload.get("checksum"),
        )
        session.add(document)
        await session.flush()
        return document

    async def list_documents(self, session: AsyncSession) -> list[KnowledgeDocument]:
        result = await session.execute(select(KnowledgeDocument).order_by(KnowledgeDocument.update_time.desc()).limit(100))
        return list(result.scalars())

    async def publish(self, session: AsyncSession, document_id: str) -> KnowledgeDocument:
        document = await session.get(KnowledgeDocument, document_id)
        if not document:
            raise LookupError("知识文档不存在")
        old = await session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
        )
        chunks = list(old.scalars())
        for chunk in chunks:
            chunk.active = False
        new_chunks = self._split(document)
        session.add_all(new_chunks)
        await session.flush()
        await self.qdrant.upsert(new_chunks)
        for chunk in new_chunks:
            chunk.active = True
        previous_result = await session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id != document.id,
                KnowledgeDocument.course_id == document.course_id,
                KnowledgeDocument.source_type == document.source_type,
                KnowledgeDocument.source_id == document.source_id,
                KnowledgeDocument.status == "ACTIVE",
            )
        )
        for previous in previous_result.scalars():
            previous.status = "ARCHIVED"
            await session.execute(
                update(KnowledgeChunk)
                .where(KnowledgeChunk.document_id == previous.id)
                .values(active=False, update_time=now_utc())
            )
        document.status = "ACTIVE"
        document.update_time = now_utc()
        await session.flush()
        return document

    async def archive_course(self, course_id: int) -> None:
        """Immediately hide all knowledge versions for a course and remove vectors."""
        from app.persistence.db import SessionFactory

        async with SessionFactory() as session:
            await session.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.course_id == course_id)
                .values(status="ARCHIVED", update_time=now_utc())
            )
            await session.execute(
                update(KnowledgeChunk)
                .where(KnowledgeChunk.course_id == course_id)
                .values(active=False, update_time=now_utc())
            )
            await session.commit()
        await self.qdrant.delete_course(course_id)

    async def search(self, session: AsyncSession, identity: Identity, course_id: int, query: str, section_id: int | None = None, limit: int = 8) -> list[SearchHit]:
        filters = [
            KnowledgeChunk.active.is_(True),
            KnowledgeChunk.course_id == course_id,
            KnowledgeDocument.status == "ACTIVE",
            KnowledgeDocument.visibility.in_(("PUBLIC", "ENROLLED")),
        ]
        if section_id:
            filters.append(or_(KnowledgeChunk.section_id.is_(None), KnowledgeChunk.section_id == section_id))
        result = await session.execute(
            select(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(and_(*filters))
        )
        chunks = list(result.scalars())
        terms = self._terms(query)
        lexical: list[tuple[KnowledgeChunk, float]] = []
        for chunk in chunks:
            text = f"{chunk.title} {chunk.content}".lower()
            score = sum(1 for term in terms if term in text) / max(1, len(terms))
            if score > 0:
                lexical.append((chunk, score))
        lexical.sort(key=lambda item: item[1], reverse=True)
        dense = await self.qdrant.search(query, course_id, section_id, limit)
        allowed = {chunk.id: chunk for chunk in chunks}
        fused: dict[str, tuple[SearchHit, float]] = {}
        for rank, (chunk, _) in enumerate(lexical, start=1):
            hit = self._hit(chunk, 1 / (60 + rank))
            fused[chunk.id] = (hit, hit.score)
        for rank, item in enumerate(dense, start=1):
            chunk_id = str(item.get("chunk_id") or item.get("chunkId") or "")
            chunk = allowed.get(chunk_id)
            if not chunk:
                continue
            score = 1 / (60 + rank)
            if chunk_id in fused:
                existing, old_score = fused[chunk_id]
                fused[chunk_id] = (existing, old_score + score)
            else:
                fused[chunk_id] = (self._hit(chunk, score), score)
        hits = [replace(hit, score=score) for hit, score in fused.values()]
        hits = sorted(hits, key=lambda item: item.score, reverse=True)[:limit]
        return await self.rerank.rerank(query, hits)

    def _split(self, document: KnowledgeDocument) -> list[KnowledgeChunk]:
        timed = decode_segments(document.content)
        if not timed:
            # Keep ordinary files on LangChain's recursive splitter so
            # paragraph/sentence boundaries and overlap are consistent across
            # ingestion paths. Subtitle segments retain their timeline-aware
            # splitter below.
            source = Document(
                page_content=document.content,
                metadata={
                    "courseId": document.course_id,
                    "chapterId": document.chapter_id,
                    "sectionId": document.section_id,
                    "sourceId": document.source_id,
                    "title": document.title,
                },
            )
            pieces = split_documents([source], chunk_size=1600, chunk_overlap=160)
            return [self._chunk(document, piece.page_content, index, page_number=piece.metadata.get("page")) for index, piece in enumerate(pieces)]
        paragraphs = (
            [(item.start_moment, item.end_moment, item.text) for item in timed]
            if timed
            else [(None, None, part.strip()) for part in re.split(r"\n\s*\n|(?<=[。！？.!?])\s+", document.content) if part.strip()]
        )
        expanded: list[tuple[int | None, int | None, str]] = []
        for start_moment, end_moment, paragraph in paragraphs:
            while len(paragraph) > 1600:
                expanded.append((start_moment, None, paragraph[:1600]))
                paragraph = paragraph[1600:]
                start_moment = None
            expanded.append((start_moment, end_moment, paragraph))
        chunks: list[KnowledgeChunk] = []
        current = ""
        current_start: int | None = None
        current_end: int | None = None
        index = 0
        for start_moment, end_moment, paragraph in expanded:
            if current and len(current) + len(paragraph) + 1 > 1600:
                chunks.append(self._chunk(document, current, index, current_start, current_end))
                current = ""
                current_start = current_end = None
                index += 1
            current = f"{current}\n{paragraph}".strip()
            current_start = start_moment if current_start is None else current_start
            current_end = end_moment if end_moment is not None else current_end
        if current:
            chunks.append(self._chunk(document, current, index, current_start, current_end))
        return chunks

    def _chunk(self, document: KnowledgeDocument, content: str, index: int, start_moment: int | None = None, end_moment: int | None = None, page_number: int | None = None) -> KnowledgeChunk:
        return KnowledgeChunk(
            document_id=document.id,
            course_id=document.course_id,
            chapter_id=document.chapter_id,
            section_id=document.section_id,
            source_type=document.source_type,
            source_id=document.source_id,
            title=document.title,
            content=content[:6000],
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            chunk_index=index,
            start_moment=start_moment,
            end_moment=end_moment,
            page_number=page_number or self._page_from_content(content),
            active=False,
            embedding_model=self.settings.embedding_model,
        )

    def _hit(self, chunk: KnowledgeChunk, score: float) -> SearchHit:
        return SearchHit(chunk.id, chunk.title, chunk.content, chunk.source_type, chunk.source_id, chunk.course_id, chunk.chapter_id, chunk.section_id, chunk.start_moment, chunk.end_moment, score, chunk.page_number)

    def _hit_from_dict(self, metadata: dict[str, Any], content: str) -> SearchHit:
        return SearchHit(
            str(metadata.get("chunkId") or metadata.get("chunk_id") or ""),
            str(metadata.get("title") or ""),
            content,
            str(metadata.get("sourceType") or metadata.get("source_type") or ""),
            metadata.get("sourceId") or metadata.get("source_id"),
            metadata.get("courseId") or metadata.get("course_id"),
            metadata.get("chapterId") or metadata.get("chapter_id"),
            metadata.get("sectionId") or metadata.get("section_id"),
            metadata.get("startMoment") or metadata.get("start_moment"),
            metadata.get("endMoment") or metadata.get("end_moment"),
            float(metadata.get("score") or 0),
            metadata.get("page") or metadata.get("page_number"),
        )

    def _page_from_content(self, content: str) -> int | None:
        match = re.search(r"\[page:(\d+)\]", content, re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _terms(self, text: str) -> set[str]:
        normalized = text.lower()
        words = set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", normalized))
        for token in re.findall(r"[\u4e00-\u9fff]+", normalized):
            words.update(token[index : index + 2] for index in range(len(token) - 1))
        return {word for word in words if len(word) >= 1}

    def _clean(self, content: str) -> str:
        content = re.sub(r"(?is)<script.*?>.*?</script>", " ", content)
        content = re.sub(r"<[^>]+>", " ", content)
        return content.replace("\x00", " ").strip()


class CourseKnowledgeRetriever(BaseRetriever):
    """LangChain retriever that preserves qhkt's relational ACL checks."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    course_id: int
    section_id: int | None = None
    limit: int = 8
    _service: KnowledgeService = PrivateAttr()
    _session: AsyncSession = PrivateAttr()
    _identity: Identity = PrivateAttr()

    def __init__(self, service: KnowledgeService, session: AsyncSession, identity: Identity, course_id: int, section_id: int | None = None, limit: int = 8) -> None:
        super().__init__(course_id=course_id, section_id=section_id, limit=limit)
        self._service = service
        self._session = session
        self._identity = identity

    def _get_relevant_documents(self, query: str, *, run_manager: Any = None) -> list[Document]:
        raise RuntimeError("CourseKnowledgeRetriever 只能通过异步接口调用")

    async def _aget_relevant_documents(self, query: str, *, run_manager: Any = None) -> list[Document]:
        hits = await self._service.search(self._session, self._identity, self.course_id, query, self.section_id, self.limit)
        return [Document(page_content=hit.content, metadata=hit.as_dict()) for hit in hits]
