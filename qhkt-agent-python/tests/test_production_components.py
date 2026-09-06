from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.observability.evaluation import EvaluationCase, evaluate_cases, redact_trace
from app.persistence.models import Base, Message
from app.rag.embedding import EmbeddingService
from app.rag.loaders import load_documents, split_documents
from app.services.memory import build_token_bounded_summary, estimate_tokens, upsert_memory_fact


def test_document_loaders_and_splitter_preserve_metadata():
    documents = load_documents("lesson.md", "# 标题\n\n课程内容".encode(), metadata={"courseId": 9})
    chunks = split_documents(documents, chunk_size=20, chunk_overlap=5)
    assert chunks
    assert all(chunk.metadata["courseId"] == 9 for chunk in chunks)


def test_production_rejects_hash_embedding():
    service = EmbeddingService(Settings(app_env="production", embedding_provider="LOCAL_HASH"))
    with pytest.raises(RuntimeError, match="LOCAL_HASH"):
        service.embed("测试")


def test_memory_summary_uses_token_budget():
    messages = [Message(role="USER", content="一二三四", user_id=1, conversation_id="c"), Message(role="ASSISTANT", content="answer", user_id=1, conversation_id="c")]
    assert estimate_tokens("一二三四") == 4
    summary = build_token_bounded_summary(messages, max_tokens=20)
    assert summary and "user:" in summary


def test_evaluation_gate_and_trace_redaction():
    case = EvaluationCase("progress", "查看进度", "progress", "get_learning_progress", True)
    result = evaluate_cases([case], [{"capability": "progress", "tool": "get_learning_progress", "citations": [{"chunkId": "1"}], "answer": "当前进度"}])
    assert result.passed
    assert redact_trace({"Authorization": "secret", "nested": "x"}) == {"Authorization": "[REDACTED]", "nested": "x"}


@pytest.mark.asyncio
async def test_long_term_memory_rejects_non_whitelisted_fact(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        with pytest.raises(ValueError, match="不允许"):
            await upsert_memory_fact(session, 1, "password", "secret")
    await engine.dispose()
