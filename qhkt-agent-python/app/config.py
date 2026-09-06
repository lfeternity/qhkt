from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _csv_ints(value: str) -> frozenset[int]:
    result: set[int] = set()
    for item in (value or "").split(","):
        item = item.strip()
        if item:
            try:
                result.add(int(item))
            except ValueError:
                continue
    return frozenset(result)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8094
    database_url: str = "sqlite+aiosqlite:///./qhkt-agent-python.db"
    db_auto_create: bool = True

    ai_enabled: bool = False
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_chat_model: str = "gpt-4o-mini"
    ai_temperature: float = 0.2
    ai_timeout_seconds: float = 30.0
    ai_max_retries: int = Field(default=1, ge=0, le=3)
    ai_max_tool_calls: int = Field(default=4, ge=1, le=8)
    ai_fallback_enabled: bool = True

    # The model transport is intentionally kept in app.agent.model. These
    # settings only control the LangChain/LangGraph orchestration around it.
    agent_runtime: str = "langgraph"
    max_graph_steps: int = Field(default=12, ge=1, le=50)
    graph_node_timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    graph_checkpoint_ttl_seconds: int = Field(default=604800, ge=60)
    memory_context_token_limit: int = Field(default=1000, ge=128, le=8000)

    jwt_enabled: bool = False
    jwt_jwks_url: str = ""
    jwt_issuer: str = ""
    jwt_audience: str = ""
    trust_gateway_headers: bool = True

    course_service_url: str = "http://localhost:8086"
    learning_service_url: str = "http://localhost:8090"
    exam_service_url: str = "http://localhost:8089"
    search_service_url: str = "http://localhost:8083"
    business_timeout_seconds: float = 3.0
    business_max_retries: int = Field(default=1, ge=0, le=3)
    mock_business_mode: bool = True

    redis_url: str = ""
    redis_password: str = ""
    redis_memory_enabled: bool = False
    rate_limit_enabled: bool = True
    requests_per_minute: int = 20
    concurrent_streams: int = 2
    messages_per_day: int = 200

    qdrant_enabled: bool = False
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "course_knowledge_v1"
    qdrant_api_key: str = ""
    embedding_provider: str = "LOCAL_HASH"
    embedding_model: str = "local-hash-v1"
    embedding_dimension: int = 1536
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_timeout_seconds: float = 20.0

    rerank_enabled: bool = False
    rerank_base_url: str = ""
    rerank_api_key: str = ""
    rerank_model: str = "rerank-v1"
    rerank_timeout_seconds: float = 10.0
    rerank_top_n: int = 8

    asr_enabled: bool = False
    asr_base_url: str = ""
    asr_api_key: str = ""
    asr_model: str = "whisper-1"
    asr_timeout_seconds: float = 60.0

    rabbitmq_url: str = ""
    mq_enabled: bool = False
    knowledge_ingestion_user_id: int = 1
    ingestion_worker_enabled: bool = True

    admin_user_ids: str = "1"
    admin_role_ids: str = ""
    teacher_role_ids: str = ""
    prompt_version: str = "learning-agent-v1"
    prompt_key: str = "learning-assistant"
    ai_input_price_micros: int = 0
    ai_output_price_micros: int = 0
    langsmith_tracing: bool = False
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str = ""
    langsmith_project: str = "qhkt-agent"
    langsmith_privacy_mode: bool = True

    media_service_url: str = "http://localhost:8087"
    object_storage_enabled: bool = False
    object_storage_bucket: str = "qhkt-agent"
    object_storage_endpoint: str = ""
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""
    object_storage_region: str = "cn-hangzhou"
    log_level: str = "INFO"

    @model_validator(mode="before")
    @classmethod
    def load_secret_files(cls, values: object) -> object:
        """Allow Docker/Kubernetes secret files without exposing values in env listings."""
        if not isinstance(values, dict):
            values = {}
        result = dict(values)
        secret_fields = {
            "ai_api_key", "embedding_api_key", "redis_password", "qdrant_api_key",
            "rabbitmq_url", "langsmith_api_key", "object_storage_access_key",
            "object_storage_secret_key", "database_url",
        }
        for field_name in secret_fields:
            env_name = field_name.upper()
            path = os.getenv(f"{env_name}_FILE")
            if not path:
                continue
            try:
                value = Path(path).read_text(encoding="utf-8").strip()
            except OSError as error:
                raise ValueError(f"无法读取密钥文件: {env_name}_FILE") from error
            if value:
                result[field_name] = value
        return result

    @property
    def admin_users(self) -> frozenset[int]:
        return _csv_ints(self.admin_user_ids)

    @property
    def admin_roles(self) -> frozenset[int]:
        return _csv_ints(self.admin_role_ids)

    @property
    def teacher_roles(self) -> frozenset[int]:
        return _csv_ints(self.teacher_role_ids)

    @property
    def production_mode(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}

    def validate_production(self) -> None:
        """Fail fast instead of silently starting a partial production stack."""
        if not self.production_mode:
            return
        required = {
            "DATABASE_URL": self.database_url if self.database_url.startswith(("mysql+", "mysql://")) else "",
            "REDIS_URL": self.redis_url,
            "QDRANT_ENABLED": self.qdrant_enabled,
            "REDIS_MEMORY_ENABLED": self.redis_memory_enabled,
            "OBJECT_STORAGE_ENABLED": self.object_storage_enabled,
            "LANGSMITH_TRACING": self.langsmith_tracing,
            "LANGSMITH_API_KEY": self.langsmith_api_key,
            "EMBEDDING_PROVIDER": self.embedding_provider.upper() != "LOCAL_HASH",
            "EMBEDDING_BASE_URL": self.embedding_base_url,
            "EMBEDDING_API_KEY": self.embedding_api_key,
        }
        if self.ai_enabled:
            required["AI_API_KEY"] = self.ai_api_key
        if self.mq_enabled:
            required["RABBITMQ_URL"] = self.rabbitmq_url
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"生产配置缺少必需项: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
