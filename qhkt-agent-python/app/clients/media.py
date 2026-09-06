from __future__ import annotations

import hashlib
from typing import Any

import httpx

from app.config import Settings


class MediaUnavailable(RuntimeError):
    pass


class MediaClient:
    """Internal client for qhkt-media, whose storage implementation is OSS-backed."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(base_url=settings.media_service_url.rstrip("/"), timeout=settings.business_timeout_seconds)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.object_storage_enabled)

    async def upload(self, filename: str, content: bytes, content_type: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise MediaUnavailable("对象存储未启用")
        try:
            response = await self._client.post("/files", files={"file": (filename, content, content_type or "application/octet-stream")})
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise MediaUnavailable("媒资服务暂时不可用") from error
        data = body.get("data", body) if isinstance(body, dict) else body
        if not isinstance(data, dict):
            raise MediaUnavailable("媒资服务响应无效")
        return {
            "fileId": data.get("id"),
            "objectKey": data.get("key") or data.get("path"),
            "path": data.get("path"),
            "filename": data.get("filename") or filename,
            "size": len(content),
            "checksum": hashlib.sha256(content).hexdigest(),
            "mimeType": content_type or "application/octet-stream",
        }

    async def info(self, file_id: int | str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        try:
            response = await self._client.get(f"/files/{file_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise MediaUnavailable("媒资服务暂时不可用") from error
        data = body.get("data", body) if isinstance(body, dict) else body
        return data if isinstance(data, dict) else None

    async def download(self, file_id: int | str) -> bytes:
        if not self.enabled:
            raise MediaUnavailable("对象存储未启用")
        try:
            response = await self._client.get(f"/files/{file_id}/content")
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as error:
            raise MediaUnavailable("媒资文件读取失败") from error

    async def delete(self, file_id: int | str) -> None:
        if not self.enabled:
            return
        try:
            response = await self._client.delete(f"/files/{file_id}")
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise MediaUnavailable("媒资文件删除失败") from error

    async def health(self) -> bool:
        if not self.enabled:
            return False
        for path in ("/health", "/actuator/health"):
            try:
                response = await self._client.get(path)
                if response.is_success:
                    return True
            except httpx.HTTPError:
                continue
        return False

    async def close(self) -> None:
        await self._client.aclose()
