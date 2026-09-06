from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from app.agent.model import ModelClient
from app.agent.tools import ToolRegistry
from app.api.routes_actions import router as actions_router
from app.api.routes_admin import router as admin_router
from app.api.routes_chat import router as chat_router
from app.api.routes_conversations import router as conversations_router
from app.api.routes_feedback import router as feedback_router
from app.api.routes_profile import router as profile_router
from app.clients.asr import ASRClient
from app.clients.business import BusinessClient
from app.clients.media import MediaClient
from app.config import get_settings
from app.graph.agent import LangGraphAgent
from app.graph.checkpoint import build_checkpointer
from app.observability.langsmith import configure_langsmith
from app.observability.metrics import REQUEST_LATENCY, REQUESTS, render
from app.observability.tracing import tracer
from app.persistence.db import engine, init_db
from app.rag.embedding import EmbeddingService
from app.rag.qdrant_store import QdrantStore
from app.rag.rerank import RerankService
from app.rag.service import KnowledgeService
from app.security.rate_limit import RateLimiter
from app.services.chat import ChatService
from app.services.events import EventStreamStore, WebSocketTicketStore
from app.services.memory import RedisConversationMemory
from app.workers.ingestion import run_worker
from app.workers.messaging import run_course_event_consumer

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_production()
    await init_db()
    configure_langsmith(settings)
    embeddings = EmbeddingService(settings)
    qdrant = QdrantStore(settings, embeddings)
    knowledge = KnowledgeService(settings, qdrant, embeddings, RerankService(settings))
    business = BusinessClient(settings)
    asr = ASRClient(settings)
    media = MediaClient(settings)
    registry = ToolRegistry(business, knowledge)
    model = ModelClient(settings)
    checkpointer, persistent_checkpoint = await build_checkpointer(settings)
    short_term_memory = RedisConversationMemory(settings)
    event_store = EventStreamStore(settings)
    ticket_store = WebSocketTicketStore(settings)
    app.state.business = business
    app.state.asr = asr
    app.state.media = media
    app.state.knowledge = knowledge
    app.state.qdrant = qdrant
    app.state.chat_service = ChatService(LangGraphAgent(settings, model, registry, checkpointer), short_term_memory)
    app.state.short_term_memory = short_term_memory
    app.state.event_store = event_store
    app.state.ticket_store = ticket_store
    app.state.graph_checkpointer = checkpointer
    app.state.persistent_checkpoint = persistent_checkpoint
    app.state.rate_limiter = RateLimiter(settings)
    stop_worker = asyncio.Event()
    app.state.ingestion_task = asyncio.create_task(run_worker(knowledge, stop_worker, media)) if settings.ingestion_worker_enabled else None
    app.state.mq_task = asyncio.create_task(run_course_event_consumer(settings, knowledge, business, stop_worker)) if settings.mq_enabled else None
    yield
    stop_worker.set()
    if app.state.ingestion_task:
        await app.state.ingestion_task
    if app.state.mq_task:
        await app.state.mq_task
    await app.state.rate_limiter.close()
    await business.close()
    await asr.close()
    await media.close()
    await short_term_memory.close()
    await event_store.close()
    await ticket_store.close()
    redis_client = getattr(checkpointer, "redis_client", None) or getattr(checkpointer, "_redis", None)
    if redis_client is not None and hasattr(redis_client, "aclose"):
        await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title="qhkt Python Agent", version="0.1.0", lifespan=lifespan)
app.include_router(conversations_router)
app.include_router(chat_router)
app.include_router(actions_router)
app.include_router(feedback_router)
app.include_router(profile_router)
app.include_router(admin_router)


def _error_response(request: Request, status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": status_code,
            "msg": message,
            "data": None,
            "requestId": getattr(request.state, "request_id", None),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception(request: Request, exception: HTTPException):
    detail = exception.detail if isinstance(exception.detail, str) else "请求失败"
    return _error_response(request, exception.status_code, detail)


@app.exception_handler(RequestValidationError)
async def validation_exception(request: Request, _: RequestValidationError):
    return _error_response(request, 422, "请求参数无效")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = request.headers.get("requestId") or uuid.uuid4().hex
    started = time.perf_counter()
    with tracer.start_as_current_span("agent.http.request") as span:
        span.set_attribute("http.request.method", request.method)
        span.set_attribute("url.path", request.url.path)
        try:
            response = await call_next(request)
        except Exception as error:
            span.record_exception(error)
            response = _error_response(request, 500, "AI 助教暂时不可用，请稍后重试")
            response.headers["requestId"] = request.state.request_id
            metric_path = getattr(request.scope.get("route"), "path", request.url.path)
            REQUESTS.labels(request.method, metric_path, "500").inc()
            REQUEST_LATENCY.labels(request.method, metric_path).observe(time.perf_counter() - started)
            return response
        span.set_attribute("http.response.status_code", response.status_code)
    response.headers["requestId"] = request.state.request_id
    metric_path = getattr(request.scope.get("route"), "path", request.url.path)
    REQUESTS.labels(request.method, metric_path, str(response.status_code)).inc()
    REQUEST_LATENCY.labels(request.method, metric_path).observe(time.perf_counter() - started)
    return response


async def _ping_dependencies(request: Request) -> dict[str, str]:
    result = {"database": "UP"}
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        result["database"] = "DOWN"
    persistent_checkpoint = bool(getattr(request.app.state, "persistent_checkpoint", False))
    if persistent_checkpoint:
        saver = getattr(request.app.state, "graph_checkpointer", None)
        redis_client = getattr(saver, "redis_client", None) or getattr(saver, "_redis", None)
        try:
            if redis_client is None:
                raise RuntimeError("redis client missing")
            await redis_client.ping()
        except Exception:
            result["redisCheckpoint"] = "DOWN"
        else:
            result["redisCheckpoint"] = "UP"
    else:
        result["redisCheckpoint"] = "DOWN" if settings.production_mode else "DISABLED"
    if settings.qdrant_enabled:
        try:
            qdrant = getattr(request.app.state, "qdrant", None)
            if qdrant is None:
                raise RuntimeError("qdrant client missing")
            await qdrant.ensure_collection()
        except Exception:
            result["qdrant"] = "DOWN"
        else:
            result["qdrant"] = "UP"
    else:
        result["qdrant"] = "DISABLED"
    if settings.object_storage_enabled:
        media = getattr(request.app.state, "media", None)
        result["objectStorage"] = "UP" if media and await media.health() else "DOWN"
    else:
        result["objectStorage"] = "DISABLED"
    if settings.langsmith_tracing:
        result["langsmith"] = "UP" if settings.langsmith_api_key else "DOWN"
    else:
        result["langsmith"] = "DISABLED"
    return result


@app.get("/api/v1/health")
async def health(request: Request):
    dependencies = await _ping_dependencies(request)
    status = "UP" if all(value != "DOWN" for value in dependencies.values()) else "DOWN"
    return {"code": 200 if status == "UP" else 503, "msg": "OK" if status == "UP" else "依赖服务未就绪", "data": {"status": status, "aiEnabled": bool(settings.ai_enabled and settings.ai_api_key), "qdrantEnabled": settings.qdrant_enabled, "dependencies": dependencies}, "requestId": request.state.request_id}


@app.get("/actuator/health")
async def actuator_health():
    return {"status": "UP"}


@app.get("/metrics")
async def metrics():
    body, content_type = render()
    return PlainTextResponse(content=body.decode("utf-8"), media_type=content_type.split(";", 1)[0])
