from __future__ import annotations

import httpx

from app.config import Settings


class ASRUnavailable(RuntimeError):
    pass


class ASRClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.asr_enabled and self.settings.asr_base_url and self.settings.asr_api_key)

    async def transcribe(self, filename: str, content: bytes, content_type: str | None) -> str:
        if not self.enabled:
            raise ASRUnavailable("ASR 未启用")
        headers = {"Authorization": f"Bearer {self.settings.asr_api_key}"}
        files = {"file": (filename, content, content_type or "application/octet-stream")}
        data = {"model": self.settings.asr_model, "response_format": "json"}
        try:
            async with httpx.AsyncClient(timeout=self.settings.asr_timeout_seconds) as client:
                response = await client.post(f"{self.settings.asr_base_url.rstrip('/')}/audio/transcriptions", headers=headers, files=files, data=data)
                response.raise_for_status()
                value = response.json()
            text = str(value.get("text") or "").strip() if isinstance(value, dict) else ""
            if not text:
                raise ValueError("ASR 返回为空")
            return text
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise ASRUnavailable("ASR 服务暂时不可用") from error

    async def close(self) -> None:
        return None
