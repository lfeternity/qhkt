from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agent.engine import AgentEngine
from app.agent.model import ModelClient
from app.agent.tools import ToolRegistry
from app.clients.business import BusinessClient
from app.config import Settings
from app.main import app
from app.persistence.db import get_session
from app.persistence.models import Base
from app.rag.embedding import EmbeddingService
from app.rag.qdrant_store import QdrantStore
from app.rag.rerank import RerankService
from app.rag.service import KnowledgeService
from app.security.rate_limit import RateLimiter
from app.services.chat import ChatService


@pytest_asyncio.fixture
async def test_env(tmp_path) -> AsyncIterator[AsyncClient]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    settings = Settings(
        database_url=database_url,
        db_auto_create=False,
        mock_business_mode=True,
        rate_limit_enabled=False,
        trust_gateway_headers=True,
        admin_user_ids="1",
    )
    db_engine = create_async_engine(database_url)
    async with db_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    business = BusinessClient(settings)
    embeddings = EmbeddingService(settings)
    knowledge = KnowledgeService(settings, QdrantStore(settings, embeddings), embeddings, RerankService(settings))
    app.state.business = business
    app.state.knowledge = knowledge
    app.state.chat_service = ChatService(AgentEngine(settings, ModelClient(settings), ToolRegistry(business, knowledge)))
    app.state.rate_limiter = RateLimiter(settings)
    app.state.test_session_factory = session_factory
    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        await app.state.rate_limiter.close()
        await db_engine.dispose()


def auth(user_id: int, role_id: int | None = None) -> dict[str, str]:
    headers = {"user-info": str(user_id), "requestId": f"test-{user_id}"}
    if role_id is not None:
        headers["role-info"] = str(role_id)
    return headers
