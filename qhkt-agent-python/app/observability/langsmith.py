from __future__ import annotations

import os
from typing import Any

from app.config import Settings
from app.observability.metrics import LANGSMITH_EXPORT_FAILURES


def configure_langsmith(settings: Settings) -> None:
    """Configure LangChain's native tracer without leaking secrets into logs."""
    enabled = bool(settings.langsmith_tracing and settings.langsmith_api_key)
    os.environ["LANGCHAIN_TRACING_V2"] = "true" if enabled else "false"
    os.environ["LANGSMITH_TRACING"] = "true" if enabled else "false"
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_endpoint:
        os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    if settings.langsmith_api_key:
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key


def tracer_for(settings: Settings) -> Any | None:
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        return None
    try:
        from langchain.callbacks.tracers import LangChainTracer
        from langsmith import Client

        client = Client(api_url=settings.langsmith_endpoint, api_key=settings.langsmith_api_key)
        return LangChainTracer(project_name=settings.langsmith_project, client=client)
    except Exception:
        LANGSMITH_EXPORT_FAILURES.inc()
        return None
