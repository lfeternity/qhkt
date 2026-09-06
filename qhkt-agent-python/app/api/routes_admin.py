from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import ok
from app.api.schemas import KnowledgeDocumentRequest, PromptRequest
from app.clients.asr import ASRUnavailable
from app.clients.media import MediaUnavailable
from app.persistence.db import get_session
from app.persistence.models import IngestionJob, KnowledgeDocument, PromptVersion, model_to_dict
from app.rag.loaders import load_documents
from app.rag.transcript import encode_segments, parse_subtitle
from app.security.identity import Identity, get_identity, require_admin, require_knowledge_uploader

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


async def _upload_object(request: Request, filename: str, content: bytes, content_type: str | None) -> dict[str, object]:
    media = getattr(request.app.state, "media", None)
    if media is None or not media.enabled:
        return {}
    try:
        return await media.upload(filename, content, content_type)
    except MediaUnavailable as error:
        raise HTTPException(status_code=503, detail="对象存储暂时不可用") from error


async def _cleanup_object(request: Request, object_info: dict[str, object]) -> None:
    file_id = object_info.get("fileId")
    media = getattr(request.app.state, "media", None)
    if not file_id or media is None:
        return
    try:
        await media.delete(file_id)
    except Exception:
        # Compensation is best effort; the original failure remains the
        # response and the media service can reconcile orphaned objects later.
        return


@router.post("/knowledge/documents")
async def create_knowledge(request: Request, request_body: KnowledgeDocumentRequest, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    require_knowledge_uploader(identity)
    service = request.app.state.knowledge
    try:
        document = await service.create_document(session, request_body.model_dump(by_alias=True))
        await session.commit()
        return ok(model_to_dict(document), identity)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/knowledge/documents")
async def list_knowledge(identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    require_knowledge_uploader(identity)
    result = await session.execute(select(KnowledgeDocument).order_by(KnowledgeDocument.update_time.desc()).limit(100))
    return ok([model_to_dict(item) for item in result.scalars()], identity)


@router.post("/knowledge/documents/{document_id}:publish")
async def publish_knowledge(document_id: str, request: Request, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    require_admin(identity)
    try:
        document = await request.app.state.knowledge.publish(session, document_id)
        await session.commit()
        return ok(model_to_dict(document), identity)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/knowledge/documents/{document_id}:reindex")
async def reindex_knowledge(document_id: str, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    require_admin(identity)
    document = await session.get(KnowledgeDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="知识文档不存在")
    job = IngestionJob(document_id=document_id, requested_by=identity.user_id, status="PENDING", stage="QUEUED")
    session.add(job)
    await session.commit()
    return ok(model_to_dict(job), identity)


@router.post("/knowledge/files")
async def upload_knowledge_file(
    request: Request,
    file: UploadFile = File(...),
    course_id: int | None = Form(default=None, alias="courseId", gt=0),
    title: str | None = Form(default=None, max_length=300),
    chapter_id: int | None = Form(default=None, alias="chapterId"),
    section_id: int | None = Form(default=None, alias="sectionId"),
    visibility: str = Form(default="ENROLLED", max_length=16),
    identity: Identity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    require_knowledge_uploader(identity)
    if not course_id:
        raise HTTPException(status_code=422, detail="courseId 不能为空")
    if not file.filename:
        raise HTTPException(status_code=400, detail="知识文件名不能为空")
    raw = await file.read(50_000_001)
    if len(raw) > 50_000_000:
        raise HTTPException(status_code=413, detail="知识文件不能超过 50MB")
    try:
        documents = load_documents(file.filename, raw, metadata={"courseId": course_id, "chapterId": chapter_id, "sectionId": section_id})
        content = "\n\n".join(
            f"[page:{item.metadata['page']}]\n{item.page_content}" if item.metadata.get("page") else item.page_content
            for item in documents
        )
        object_info = await _upload_object(request, file.filename, raw, file.content_type)
        document = await request.app.state.knowledge.create_document(session, {
            "courseId": course_id,
            "chapterId": chapter_id,
            "sectionId": section_id,
            "sourceType": "FILE",
            "sourceId": str(object_info.get("fileId") or file.filename),
            "title": (title or file.filename.rsplit(".", 1)[0])[:300],
            "content": content,
            "visibility": visibility.strip().upper(),
            "objectFileId": object_info.get("fileId"),
            "objectKey": object_info.get("objectKey"),
            "mimeType": object_info.get("mimeType") or file.content_type,
            "fileSize": object_info.get("size") or len(raw),
            "checksum": object_info.get("checksum"),
        })
        job = IngestionJob(document_id=document.id, requested_by=identity.user_id, status="PENDING", stage="QUEUED")
        session.add(job)
        await session.commit()
        return ok({"document": model_to_dict(document), "job": model_to_dict(job)}, identity)
    except UnicodeDecodeError as error:
        await session.rollback()
        await _cleanup_object(request, locals().get("object_info", {}))
        raise HTTPException(status_code=400, detail="知识文件必须使用 UTF-8 编码") from error
    except (RuntimeError, ValueError) as error:
        await session.rollback()
        await _cleanup_object(request, locals().get("object_info", {}))
        raise HTTPException(status_code=400, detail=str(error)) from error
    except HTTPException:
        await session.rollback()
        await _cleanup_object(request, locals().get("object_info", {}))
        raise
    except Exception as error:
        await session.rollback()
        await _cleanup_object(request, locals().get("object_info", {}))
        raise HTTPException(status_code=500, detail="知识文件保存失败") from error


@router.post("/knowledge/transcripts")
async def upload_transcript(
    request: Request,
    file: UploadFile = File(...),
    course_id: int | None = Form(default=None, alias="courseId", gt=0),
    course_id_snake: int | None = Form(default=None, alias="course_id", gt=0),
    title: str | None = Form(default=None, max_length=300),
    chapter_id: int | None = Form(default=None, alias="chapterId"),
    chapter_id_snake: int | None = Form(default=None, alias="chapter_id"),
    section_id: int | None = Form(default=None, alias="sectionId"),
    section_id_snake: int | None = Form(default=None, alias="section_id"),
    visibility: str = Form(default="ENROLLED", max_length=16),
    identity: Identity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    require_knowledge_uploader(identity)
    course_id = course_id or course_id_snake
    chapter_id = chapter_id or chapter_id_snake
    section_id = section_id or section_id_snake
    if not course_id:
        raise HTTPException(status_code=422, detail="courseId 不能为空")
    if not file.filename:
        raise HTTPException(status_code=400, detail="字幕文件名不能为空")
    raw = await file.read(5_000_001)
    if len(raw) > 5_000_000:
        raise HTTPException(status_code=413, detail="字幕文件不能超过 5MB")
    try:
        segments = parse_subtitle(file.filename, raw.decode("utf-8-sig"))
        object_info = await _upload_object(request, file.filename, raw, file.content_type)
        document = await request.app.state.knowledge.create_document(
            session,
            {
                "courseId": course_id,
                "chapterId": chapter_id,
                "sectionId": section_id,
                "sourceType": "TRANSCRIPT",
                "sourceId": file.filename,
                "title": (title or file.filename.rsplit(".", 1)[0])[:300],
                "content": encode_segments(segments),
                "visibility": visibility.strip().upper(),
                "objectFileId": object_info.get("fileId"),
                "objectKey": object_info.get("objectKey"),
                "mimeType": object_info.get("mimeType") or file.content_type,
                "fileSize": object_info.get("size") or len(raw),
                "checksum": object_info.get("checksum"),
            },
        )
        job = IngestionJob(document_id=document.id, requested_by=identity.user_id, status="PENDING", stage="QUEUED")
        session.add(job)
        await session.commit()
        return ok({"document": model_to_dict(document), "job": model_to_dict(job)}, identity)
    except UnicodeDecodeError as error:
        await session.rollback()
        await _cleanup_object(request, locals().get("object_info", {}))
        raise HTTPException(status_code=400, detail="字幕文件必须使用 UTF-8 编码") from error
    except ValueError as error:
        await session.rollback()
        await _cleanup_object(request, locals().get("object_info", {}))
        raise HTTPException(status_code=400, detail=str(error)) from error
    except HTTPException:
        await session.rollback()
        await _cleanup_object(request, locals().get("object_info", {}))
        raise
    except Exception as error:
        await session.rollback()
        await _cleanup_object(request, locals().get("object_info", {}))
        raise HTTPException(status_code=500, detail="字幕文件保存失败") from error


@router.post("/knowledge/transcripts:asr")
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),
    course_id: int | None = Form(default=None, alias="courseId", gt=0),
    course_id_snake: int | None = Form(default=None, alias="course_id", gt=0),
    title: str | None = Form(default=None, max_length=300),
    chapter_id: int | None = Form(default=None, alias="chapterId"),
    chapter_id_snake: int | None = Form(default=None, alias="chapter_id"),
    section_id: int | None = Form(default=None, alias="sectionId"),
    section_id_snake: int | None = Form(default=None, alias="section_id"),
    visibility: str = Form(default="ENROLLED", max_length=16),
    identity: Identity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    require_knowledge_uploader(identity)
    course_id = course_id or course_id_snake
    chapter_id = chapter_id or chapter_id_snake
    section_id = section_id or section_id_snake
    if not course_id:
        raise HTTPException(status_code=422, detail="courseId 不能为空")
    if not file.filename:
        raise HTTPException(status_code=400, detail="音频文件名不能为空")
    raw = await file.read(25_000_001)
    if len(raw) > 25_000_000:
        raise HTTPException(status_code=413, detail="音频文件不能超过 25MB")
    try:
        asr = getattr(request.app.state, "asr", None)
        if asr is None:
            raise ASRUnavailable("ASR 未配置")
        text = await asr.transcribe(file.filename, raw, file.content_type)
        object_info = await _upload_object(request, file.filename, raw, file.content_type)
        document = await request.app.state.knowledge.create_document(
            session,
            {
                "courseId": course_id,
                "chapterId": chapter_id,
                "sectionId": section_id,
                "sourceType": "TRANSCRIPT",
                "sourceId": file.filename,
                "title": (title or file.filename.rsplit(".", 1)[0])[:300],
                "content": text,
                "visibility": visibility.strip().upper(),
                "objectFileId": object_info.get("fileId"),
                "objectKey": object_info.get("objectKey"),
                "mimeType": object_info.get("mimeType") or file.content_type,
                "fileSize": object_info.get("size") or len(raw),
                "checksum": object_info.get("checksum"),
            },
        )
        job = IngestionJob(document_id=document.id, requested_by=identity.user_id, status="PENDING", stage="QUEUED")
        session.add(job)
        await session.commit()
        return ok({"document": model_to_dict(document), "job": model_to_dict(job)}, identity)
    except ASRUnavailable as error:
        await session.rollback()
        await _cleanup_object(request, locals().get("object_info", {}))
        raise HTTPException(status_code=503, detail="ASR 服务暂时不可用") from error
    except ValueError as error:
        await session.rollback()
        await _cleanup_object(request, locals().get("object_info", {}))
        raise HTTPException(status_code=400, detail=str(error)) from error
    except HTTPException:
        await session.rollback()
        await _cleanup_object(request, locals().get("object_info", {}))
        raise
    except Exception as error:
        await session.rollback()
        await _cleanup_object(request, locals().get("object_info", {}))
        raise HTTPException(status_code=500, detail="音频文件保存失败") from error


@router.get("/knowledge/jobs/{job_id}")
async def get_job(job_id: str, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    require_knowledge_uploader(identity)
    job = await session.get(IngestionJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="知识摄取任务不存在")
    return ok(model_to_dict(job), identity)


@router.post("/knowledge/jobs/{job_id}:retry")
async def retry_job(job_id: str, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    require_admin(identity)
    job = await session.get(IngestionJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="知识摄取任务不存在")
    job.status, job.stage, job.retry_count, job.error_code, job.error_message = "PENDING", "QUEUED", 0, None, None
    await session.commit()
    return ok(model_to_dict(job), identity)


@router.post("/prompts")
async def create_prompt(payload: PromptRequest, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    require_admin(identity)

    content = payload.content.strip()
    key = payload.promptKey.strip()
    version = payload.version.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Prompt 内容不能为空")
    prompt = PromptVersion(prompt_key=key, version=version, content=content, content_hash=hashlib.sha256(content.encode()).hexdigest(), status="DRAFT", publisher_id=identity.user_id)
    session.add(prompt)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Prompt 版本已存在") from error
    return ok(model_to_dict(prompt), identity)


@router.get("/prompts")
async def list_prompts(identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    require_admin(identity)

    result = await session.execute(select(PromptVersion).order_by(PromptVersion.update_time.desc()).limit(100))
    return ok([model_to_dict(item) for item in result.scalars()], identity)


@router.post("/prompts/{prompt_id}:publish")
async def publish_prompt(prompt_id: str, identity: Identity = Depends(get_identity), session: AsyncSession = Depends(get_session)):
    require_admin(identity)

    prompt = await session.get(PromptVersion, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    await session.execute(update(PromptVersion).where(PromptVersion.prompt_key == prompt.prompt_key).values(status="ARCHIVED"))
    prompt.status = "ACTIVE"
    await session.commit()
    return ok(model_to_dict(prompt), identity)
