from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import Settings
from app.security.identity import Identity


class BusinessUnavailable(RuntimeError):
    pass


class BusinessClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.timeout = httpx.Timeout(settings.business_timeout_seconds)

    async def close(self) -> None:
        """Reserved for a shared client implementation; kept for lifespan symmetry."""
        return

    async def current_lesson(self, identity: Identity) -> Any:
        if self.settings.mock_business_mode:
            return {"courseId": 9, "courseName": "Agent 测试课程", "latestSectionName": "入门章节"}
        return await self._get(self.settings.learning_service_url, "/lessons/now", identity)

    async def my_lessons(self, identity: Identity, page_no: int = 1, page_size: int = 10) -> Any:
        if self.settings.mock_business_mode:
            return [{"courseId": 9, "courseName": "Agent 测试课程", "learnedSections": 2, "sections": 10}]
        return await self._get(self.settings.learning_service_url, "/lessons/page", identity, {"pageNo": page_no, "pageSize": page_size})

    async def has_course_access(self, identity: Identity, course_id: int) -> bool:
        if self.settings.mock_business_mode:
            return course_id > 0
        value = await self._get(self.settings.learning_service_url, f"/lessons/{course_id}/valid", identity)
        if isinstance(value, dict):
            value = value.get("valid", value.get("count", value.get("data", 0)))
        return bool(value)

    async def learning_progress(self, identity: Identity, course_id: int) -> Any:
        if self.settings.mock_business_mode:
            return {"courseId": course_id, "learnedSections": 2, "sections": 10, "percent": 20}
        return await self._get(self.settings.learning_service_url, f"/learning-records/course/{course_id}", identity)

    async def learning_plans(self, identity: Identity) -> Any:
        if self.settings.mock_business_mode:
            return [{"courseId": 9, "freq": 3, "status": "ACTIVE"}]
        return await self._get(self.settings.learning_service_url, "/lessons/plans", identity, {"pageNo": 1, "pageSize": 50})

    async def course_outline(self, identity: Identity, course_id: int) -> Any:
        if self.settings.mock_business_mode:
            return [{"id": 11, "name": "Agent 测试章节", "sections": [{"id": 111, "name": "第一节"}]}]
        return await self._get(self.settings.course_service_url, f"/courses/{course_id}/catalogs", identity)

    async def course_info(self, identity: Identity, course_id: int) -> Any:
        if self.settings.mock_business_mode:
            return {"id": course_id, "name": "Agent 测试课程", "description": "用于本地 Agent 验证的课程"}
        return await self._get(self.settings.course_service_url, f"/course/{course_id}", identity, {"withCatalogue": "true", "withTeachers": "false"})

    async def search_courses(self, identity: Identity, keyword: str, limit: int = 5) -> Any:
        if self.settings.mock_business_mode:
            return [{"id": 9, "name": f"{keyword}入门课程", "score": 1.0}]
        return await self._get(self.settings.search_service_url, "/courses/portal", identity, {"keyword": keyword, "pageNo": 1, "pageSize": limit})

    async def section_practice(self, identity: Identity, biz_id: int) -> Any:
        if self.settings.mock_business_mode:
            return [{"id": biz_id, "question": "以下哪项属于课程核心能力？", "options": ["A. 检索", "B. 随机猜测"]}]
        value = await self._get(self.settings.exam_service_url, "/questions/listOfBiz", identity, {"bizId": biz_id})
        return strip_answers(value)

    async def create_learning_plan(self, identity: Identity, payload: dict[str, Any], idempotency_key: str | None = None) -> Any:
        return await self._post(self.settings.learning_service_url, "/lessons/plans", identity, payload, idempotency_key)

    async def create_note(self, identity: Identity, payload: dict[str, Any], idempotency_key: str | None = None) -> Any:
        return await self._post(self.settings.learning_service_url, "/notes", identity, payload, idempotency_key)

    async def create_question(self, identity: Identity, payload: dict[str, Any], idempotency_key: str | None = None) -> Any:
        return await self._post(self.settings.learning_service_url, "/questions", identity, payload, idempotency_key)

    async def _get(self, base_url: str, path: str, identity: Identity, params: dict[str, Any] | None = None) -> Any:
        for attempt in range(self.settings.business_max_retries + 1):
            try:
                async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=self.timeout) as client:
                    response = await client.get(path, params=params, headers=self._headers(identity))
                    return self._parse(response)
            except (httpx.HTTPError, ValueError) as error:
                if attempt >= self.settings.business_max_retries or not self._retryable(error):
                    raise BusinessUnavailable("业务服务暂时不可用") from error
                await asyncio.sleep(0.1 * (attempt + 1))
        raise BusinessUnavailable("业务服务暂时不可用")

    async def _post(self, base_url: str, path: str, identity: Identity, payload: dict[str, Any], idempotency_key: str | None = None) -> Any:
        if self.settings.mock_business_mode:
            return {"accepted": True, "payload": payload, "idempotencyKey": idempotency_key}
        for attempt in range(self.settings.business_max_retries + 1):
            try:
                async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=self.timeout) as client:
                    headers = self._headers(identity)
                    if idempotency_key:
                        headers["Idempotency-Key"] = idempotency_key
                    response = await client.post(path, json=payload, headers=headers)
                    return self._parse(response)
            except (httpx.HTTPError, ValueError) as error:
                if attempt >= self.settings.business_max_retries or not idempotency_key or not self._retryable(error):
                    raise BusinessUnavailable("业务操作执行失败") from error
                await asyncio.sleep(0.1 * (attempt + 1))
        raise BusinessUnavailable("业务操作执行失败")

    def _headers(self, identity: Identity) -> dict[str, str]:
        headers = {"user-info": str(identity.user_id), "requestId": identity.request_id}
        if identity.role_id is not None:
            headers["role-info"] = str(identity.role_id)
        return headers

    def _parse(self, response: httpx.Response) -> Any:
        response.raise_for_status()
        # Several existing qhkt write endpoints intentionally return 204 or an
        # empty 200 response. An acknowledged HTTP success is still a successful
        # business operation and must not be retried as a JSON parsing failure.
        if response.status_code == 204 or not response.content.strip():
            return None
        value = response.json()
        if isinstance(value, dict) and "code" in value:
            if value.get("code") != 200:
                raise BusinessUnavailable("业务服务返回失败")
            return value.get("data")
        return value

    def _retryable(self, error: Exception) -> bool:
        return isinstance(error, (httpx.TimeoutException, httpx.NetworkError)) or (
            isinstance(error, httpx.HTTPStatusError) and error.response.status_code in {408, 425, 429, 500, 502, 503, 504}
        )


def strip_answers(value: Any) -> Any:
    if isinstance(value, dict):
        def is_answer_field(key: object) -> bool:
            normalized = str(key).lower().replace("_", "")
            return "answer" in normalized or normalized in {"analysis", "explanation", "solution"} or "解析" in str(key)

        return {key: strip_answers(item) for key, item in value.items() if not is_answer_field(key)}
    if isinstance(value, list):
        return [strip_answers(item) for item in value]
    return value
