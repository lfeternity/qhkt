from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.business import BusinessClient, strip_answers
from app.persistence.db import SessionFactory
from app.rag.service import CourseKnowledgeRetriever, KnowledgeService, SearchHit
from app.security.identity import Identity


@dataclass
class ToolContext:
    identity: Identity
    conversation_id: str
    page_context: dict[str, Any] = field(default_factory=dict)
    citations: list[SearchHit] = field(default_factory=list)
    session: AsyncSession | None = None


ToolHandler = Callable[[ToolContext, dict[str, Any]], Awaitable[Any]]


class _EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _PageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNo: int = Field(default=1, ge=1)
    pageSize: int = Field(default=10, ge=1, le=20)


class _CourseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    courseId: int = Field(gt=0)


class _SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=5, ge=1, le=10)


class _PracticeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bizId: int = Field(gt=0)
    courseId: int | None = Field(default=None, gt=0)


class _KnowledgeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)
    courseId: int | None = Field(default=None, gt=0)


class _PlanArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    courseId: int = Field(gt=0)
    freq: int = Field(ge=1, le=50)


class _NoteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=10000)
    isPrivate: bool = True


class _QuestionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=10000)
    anonymity: bool = False


class ToolRegistry:
    def __init__(self, business: BusinessClient, knowledge: KnowledgeService) -> None:
        self.business = business
        self.knowledge = knowledge
        self._handlers: dict[str, ToolHandler] = {
            "get_current_lesson": self._current_lesson,
            "get_my_lessons": self._my_lessons,
            "get_learning_progress": self._learning_progress,
            "get_course_outline": self._course_outline,
            "search_courses": self._search_courses,
            "get_section_practice": self._section_practice,
            "retrieve_course_knowledge": self._retrieve_knowledge,
            "prepare_learning_plan": self._prepare_learning_plan,
            "prepare_note": self._prepare_note,
            "prepare_question": self._prepare_question,
        }
        # Keep one authoritative map for both LangChain schemas and the
        # execution boundary. Model supplied JSON is validated again before a
        # handler can reach a downstream service.
        self._arg_models: dict[str, type[BaseModel]] = {
            "get_current_lesson": _EmptyArgs,
            "get_my_lessons": _PageArgs,
            "get_learning_progress": _CourseArgs,
            "get_course_outline": _CourseArgs,
            "search_courses": _SearchArgs,
            "get_section_practice": _PracticeArgs,
            "retrieve_course_knowledge": _KnowledgeArgs,
            "prepare_learning_plan": _PlanArgs,
            "prepare_note": _NoteArgs,
            "prepare_question": _QuestionArgs,
        }

    def schemas(self) -> list[dict[str, Any]]:
        return [
            self._schema("get_current_lesson", "查询当前登录学员最近正在学习的课程", {}),
            self._schema("get_my_lessons", "分页查询当前登录学员的课表", {"pageNo": {"type": "integer", "minimum": 1}, "pageSize": {"type": "integer", "minimum": 1, "maximum": 20}}),
            self._schema("get_learning_progress", "查询当前学员在指定已报名课程中的学习进度", {"courseId": {"type": "integer"}}, ["courseId"]),
            self._schema("get_course_outline", "查询课程的章、节和练习目录", {"courseId": {"type": "integer"}}, ["courseId"]),
            self._schema("search_courses", "按关键词搜索公开课程，不用于检索课程讲义内容", {"keyword": {"type": "string"}, "limit": {"type": "integer", "maximum": 10}}, ["keyword"]),
            self._schema("get_section_practice", "查询章节练习题干和选项，永远不返回答案和解析", {"bizId": {"type": "integer"}, "courseId": {"type": "integer"}}, ["bizId"]),
            self._schema("retrieve_course_knowledge", "从当前学员有权访问的课程资料检索答案依据和可引用来源", {"query": {"type": "string"}, "courseId": {"type": "integer"}}, ["query"]),
            self._schema("prepare_learning_plan", "准备创建每周学习计划，仅生成待确认操作，不会立即执行", {"courseId": {"type": "integer"}, "freq": {"type": "integer", "minimum": 1, "maximum": 50}}, ["courseId", "freq"]),
            self._schema("prepare_note", "准备保存当前课程笔记，仅生成待确认操作", {"content": {"type": "string"}, "isPrivate": {"type": "boolean"}}, ["content"]),
            self._schema("prepare_question", "准备发布课程问题，仅生成待确认操作", {"title": {"type": "string"}, "description": {"type": "string"}, "anonymity": {"type": "boolean"}}, ["title", "description"]),
        ]

    def langchain_tools(self, context: ToolContext) -> list[StructuredTool]:
        """Build the single Agent's typed, context-bound LangChain tools."""
        definitions = list(self._arg_models.items())
        descriptions = {item["function"]["name"]: item["function"]["description"] for item in self.schemas()}
        result: list[StructuredTool] = []
        for name, schema in definitions:
            async def invoke(_name: str = name, **kwargs: Any) -> Any:
                return await self.execute(_name, kwargs, context)

            result.append(StructuredTool.from_function(
                coroutine=invoke,
                name=name,
                description=descriptions[name],
                args_schema=schema,
            ))
        return result

    async def execute(self, name: str, arguments: dict[str, Any], context: ToolContext) -> Any:
        handler = self._handlers.get(name)
        if handler is None:
            raise ValueError("未授权的工具")
        if not isinstance(arguments, dict):
            raise TypeError("工具参数必须是对象")
        schema = self._arg_models[name]
        try:
            validated = schema.model_validate(arguments)
        except Exception as error:
            # Do not expose Pydantic internals or field values to clients.
            raise ValueError("工具参数无效") from error
        return await handler(context, validated.model_dump(exclude_none=True))

    def _schema(self, name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}}}

    async def _current_lesson(self, context: ToolContext, _: dict[str, Any]) -> Any:
        return await self.business.current_lesson(context.identity)

    async def _my_lessons(self, context: ToolContext, args: dict[str, Any]) -> Any:
        page = max(1, int(args.get("pageNo") or 1))
        size = min(20, max(1, int(args.get("pageSize") or 10)))
        return await self.business.my_lessons(context.identity, page, size)

    async def _learning_progress(self, context: ToolContext, args: dict[str, Any]) -> Any:
        course_id = self._course(context, args.get("courseId"))
        await self._require_access(context, course_id)
        return await self.business.learning_progress(context.identity, course_id)

    async def _course_outline(self, context: ToolContext, args: dict[str, Any]) -> Any:
        course_id = self._course(context, args.get("courseId"))
        await self._require_access(context, course_id)
        return await self.business.course_outline(context.identity, course_id)

    async def _search_courses(self, context: ToolContext, args: dict[str, Any]) -> Any:
        keyword = str(args.get("keyword") or "").strip()
        if not keyword or len(keyword) > 100:
            raise ValueError("课程关键词不能为空或过长")
        return await self.business.search_courses(context.identity, keyword, min(10, max(1, int(args.get("limit") or 5))))

    async def _section_practice(self, context: ToolContext, args: dict[str, Any]) -> Any:
        biz_id = int(args.get("bizId") or 0)
        if biz_id <= 0:
            raise ValueError("练习 ID 无效")
        course_id = self._course(context, args.get("courseId"))
        await self._require_access(context, course_id)
        return strip_answers(await self.business.section_practice(context.identity, biz_id))

    async def _retrieve_knowledge(self, context: ToolContext, args: dict[str, Any]) -> Any:
        query = str(args.get("query") or "").strip()
        if not query or len(query) > 1000:
            raise ValueError("检索问题不能为空或过长")
        course_id = self._course(context, args.get("courseId"))
        await self._require_access(context, course_id)
        section_id = context.page_context.get("sectionId")
        if context.session:
            retriever = CourseKnowledgeRetriever(self.knowledge, context.session, context.identity, course_id, section_id)
            documents = await retriever.ainvoke(query)
            hits = [self.knowledge._hit_from_dict(document.metadata, document.page_content) for document in documents]
        else:
            async with SessionFactory() as session:
                retriever = CourseKnowledgeRetriever(self.knowledge, session, context.identity, course_id, section_id)
                documents = await retriever.ainvoke(query)
                hits = [self.knowledge._hit_from_dict(document.metadata, document.page_content) for document in documents]
        context.citations.extend(hits)
        return [hit.as_dict() for hit in hits]

    async def _prepare_learning_plan(self, context: ToolContext, args: dict[str, Any]) -> Any:
        course_id = self._course(context, args.get("courseId"))
        await self._require_access(context, course_id)
        freq = int(args.get("freq") or 0)
        if not 1 <= freq <= 50:
            raise ValueError("每周学习频率应为 1 到 50")
        return await self._prepare(context, "CREATE_LEARNING_PLAN", {"courseId": course_id, "freq": freq}, f"为课程创建每周 {freq} 节的学习计划")

    async def _prepare_note(self, context: ToolContext, args: dict[str, Any]) -> Any:
        page = self._page(context)
        await self._require_access(context, int(page["courseId"]))
        content = str(args.get("content") or "").strip()
        if not content or len(content) > 10000:
            raise ValueError("笔记内容不能为空或过长")
        payload = {"content": content, "noteMoment": max(0, int(page.get("playMoment") or 0)), "isPrivate": bool(args.get("isPrivate", True)), "courseId": int(page["courseId"]), "chapterId": int(page["chapterId"]), "sectionId": int(page["sectionId"])}
        return await self._prepare(context, "CREATE_NOTE", payload, "保存当前小节笔记")

    async def _prepare_question(self, context: ToolContext, args: dict[str, Any]) -> Any:
        page = self._page(context)
        await self._require_access(context, int(page["courseId"]))
        title = str(args.get("title") or "").strip()
        description = str(args.get("description") or "").strip()
        if not title or not description or len(title) > 200 or len(description) > 10000:
            raise ValueError("问题标题和描述不能为空或过长")
        payload = {"title": title, "description": description, "anonymity": bool(args.get("anonymity", False)), "courseId": int(page["courseId"]), "chapterId": int(page["chapterId"]), "sectionId": int(page["sectionId"])}
        return await self._prepare(context, "CREATE_QUESTION", payload, f"发布问题：{title}")

    async def _prepare(self, context: ToolContext, action_type: str, payload: dict[str, Any], summary: str) -> Any:
        from app.services.actions import prepare_action

        if context.session:
            action = await prepare_action(context.session, context.identity.user_id, context.conversation_id, action_type, payload, summary)
            return action
        async with SessionFactory() as session:
            action = await prepare_action(session, context.identity.user_id, context.conversation_id, action_type, payload, summary)
            await session.commit()
            return action

    def _course(self, context: ToolContext, requested: Any) -> int:
        value = requested or context.page_context.get("courseId")
        try:
            course_id = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError("请先选择课程") from error
        if course_id <= 0:
            raise ValueError("请先选择课程")
        return course_id

    def _page(self, context: ToolContext) -> dict[str, Any]:
        page = context.page_context
        required = ("courseId", "chapterId", "sectionId")
        if any(page.get(key) in (None, "") for key in required):
            raise ValueError("当前页面缺少课程章节上下文")
        return page

    async def _require_access(self, context: ToolContext, course_id: int) -> None:
        if not await self.business.has_course_access(context.identity, course_id):
            raise PermissionError("无权访问该课程")
