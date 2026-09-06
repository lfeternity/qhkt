from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import or_, select, update

from app.clients.media import MediaClient
from app.persistence.db import SessionFactory
from app.persistence.models import IngestionJob, KnowledgeDocument, now_utc
from app.rag.loaders import load_documents
from app.rag.service import KnowledgeService

logger = logging.getLogger(__name__)


async def process_once(knowledge: KnowledgeService, media: MediaClient | None = None) -> None:
    async with SessionFactory() as session:
        stale_before = now_utc() - timedelta(minutes=10)
        await session.execute(
            update(IngestionJob)
            .where(IngestionJob.status == "RUNNING", IngestionJob.started_time < stale_before)
            .values(status="RETRY_WAIT", stage="FAILED", next_attempt_time=now_utc(), error_code="STALE_WORKER")
        )
        due = now_utc()
        result = await session.execute(
            select(IngestionJob)
            .where(
                or_(
                    IngestionJob.status == "PENDING",
                    (IngestionJob.status == "RETRY_WAIT")
                    & (IngestionJob.next_attempt_time.is_(None) | (IngestionJob.next_attempt_time <= due)),
                )
            )
            .order_by(IngestionJob.create_time.asc())
            .limit(5)
            .with_for_update()
        )
        jobs = list(result.scalars())
        for job in jobs:
            job.status, job.stage, job.started_time = "RUNNING", "INDEXING", now_utc()
            await session.commit()
            try:
                document = await session.get(KnowledgeDocument, job.document_id)
                if not document:
                    raise LookupError("知识文档不存在")
                if media and document.object_file_id:
                    info = await media.info(document.object_file_id)
                    raw = await media.download(document.object_file_id)
                    filename = str((info or {}).get("filename") or document.object_key or document.title)
                    loaded = load_documents(filename, raw, metadata={"courseId": document.course_id, "chapterId": document.chapter_id, "sectionId": document.section_id})
                    document.content = "\n\n".join(item.page_content for item in loaded)
                await knowledge.publish(session, document.id)
                job.status, job.stage, job.completed_time, job.error_code, job.error_message = "SUCCEEDED", "COMPLETED", now_utc(), None, None
            except Exception as error:
                job_id = job.id
                await session.rollback()
                job = await session.get(IngestionJob, job_id)
                if not job:
                    continue
                job.retry_count += 1
                job.status = "DEAD_LETTER" if job.retry_count > job.max_retries else "RETRY_WAIT"
                job.stage, job.error_code, job.error_message = "FAILED", type(error).__name__[:64], str(error)[:500]
                if job.status == "RETRY_WAIT":
                    job.next_attempt_time = now_utc() + timedelta(seconds=min(300, 2 ** job.retry_count))
            await session.commit()


async def run_worker(knowledge: KnowledgeService, stop: asyncio.Event, media: MediaClient | None = None) -> None:
    while not stop.is_set():
        try:
            await process_once(knowledge, media)
        except Exception:
            logger.exception("knowledge ingestion worker failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass
