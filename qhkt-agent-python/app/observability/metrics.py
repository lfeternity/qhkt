from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

REQUESTS = Counter("agent_http_requests_total", "Agent HTTP requests", ["method", "path", "status"])
REQUEST_LATENCY = Histogram("agent_http_request_duration_seconds", "Agent HTTP request duration", ["method", "path"])
ACTIVE_STREAMS = Gauge("agent_active_streams", "Active Agent streams")
LANGSMITH_EXPORT_FAILURES = Counter("langsmith_export_failures_total", "LangSmith tracing/export failures")


def render() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
