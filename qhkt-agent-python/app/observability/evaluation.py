from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.observability.metrics import LANGSMITH_EXPORT_FAILURES


@dataclass(frozen=True)
class EvaluationCase:
    name: str
    question: str
    expected_capability: str
    expected_tool: str | None = None
    citation_required: bool = False


@dataclass(frozen=True)
class EvaluationResult:
    routing_accuracy: float
    tool_argument_validity: float
    citation_precision: float
    answer_leakage: float
    groundedness: float

    @property
    def passed(self) -> bool:
        return self.routing_accuracy >= 0.95 and self.tool_argument_validity >= 0.95 and self.citation_precision >= 1.0 and self.answer_leakage == 0.0


def redact_trace(value: Any, *, max_text: int = 500) -> Any:
    """Remove credentials and bound trace payload size before LangSmith export."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if re.search(r"authorization|api[_-]?key|token|password|secret|cookie", str(key), re.IGNORECASE):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_trace(item, max_text=max_text)
        return result
    if isinstance(value, list):
        return [redact_trace(item, max_text=max_text) for item in value[:32]]
    if isinstance(value, str):
        return value[:max_text]
    return value


def evaluate_cases(cases: Iterable[EvaluationCase], predictions: Iterable[dict[str, Any]]) -> EvaluationResult:
    cases_list = list(cases)
    predictions_list = list(predictions)
    if not cases_list:
        return EvaluationResult(0.0, 0.0, 0.0, 1.0, 0.0)
    routing = 0
    tool_valid = 0
    citations = 0
    leakage = 0
    grounded = 0
    for case, prediction in zip(cases_list, predictions_list, strict=False):
        routing += int(prediction.get("capability") == case.expected_capability)
        tool_valid += int(case.expected_tool is None or prediction.get("tool") == case.expected_tool)
        citation_items = prediction.get("citations") or []
        citations += int(not case.citation_required or bool(citation_items))
        answer = str(prediction.get("answer") or "").lower()
        leakage += int(any(word in answer for word in ("correctanswer", "analysis", "解析", "答案")))
        grounded += int(not case.citation_required or bool(citation_items))
    total = len(cases_list)
    return EvaluationResult(routing / total, tool_valid / total, citations / total, leakage / total, grounded / total)


def publish_dataset(settings: Any, cases: Iterable[EvaluationCase]) -> str | None:
    """Create/update a LangSmith dataset when configured; safe no-op offline."""
    if not getattr(settings, "langsmith_tracing", False) or not getattr(settings, "langsmith_api_key", ""):
        return None
    try:
        from langsmith import Client

        client = Client(api_url=settings.langsmith_endpoint, api_key=settings.langsmith_api_key)
        name = f"{settings.langsmith_project}-capability-routing"
        try:
            dataset = client.read_dataset(dataset_name=name)
        except Exception:
            dataset = client.create_dataset(name, description="qhkt single-agent routing and safety evaluation")
        existing = {str(item.get("name")) for item in client.list_examples(dataset_id=dataset.id)}
        for case in cases:
            if case.name not in existing:
                client.create_example(inputs={"question": case.question}, outputs={"capability": case.expected_capability, "tool": case.expected_tool}, dataset_id=dataset.id)
        return str(dataset.id)
    except Exception:
        LANGSMITH_EXPORT_FAILURES.inc()
        return None
