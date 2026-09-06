from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings


def _http_ok(url: str, headers: dict[str, str] | None = None) -> bool:
    try:
        request = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(request, timeout=5) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def main() -> int:
    settings = Settings()
    checks: dict[str, str] = {}
    try:
        settings.validate_production()
    except ValueError as error:
        checks["configuration"] = str(error)
    else:
        checks["configuration"] = "OK"
    if settings.qdrant_enabled:
        headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
        checks["qdrant"] = "OK" if _http_ok(f"{settings.qdrant_url.rstrip('/')}/collections/{settings.qdrant_collection}", headers) else "DOWN"
    if settings.object_storage_enabled:
        checks["media"] = "OK" if _http_ok(f"{settings.media_service_url.rstrip('/')}/health") else "DOWN"
    if settings.embedding_base_url:
        checks["embeddingEndpoint"] = "CONFIGURED"
    print(json.dumps({"environment": settings.app_env, "checks": checks}, ensure_ascii=False))
    return 0 if all(value in {"OK", "CONFIGURED"} for value in checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
