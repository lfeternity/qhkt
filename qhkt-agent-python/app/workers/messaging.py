from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping

import aio_pika
from aio_pika.abc import AbstractIncomingMessage
from aio_pika.exceptions import AMQPError

from app.clients.business import BusinessClient, BusinessUnavailable
from app.config import Settings
from app.persistence.db import SessionFactory
from app.persistence.models import IngestionJob
from app.rag.service import KnowledgeService
from app.security.identity import Identity

logger = logging.getLogger(__name__)


async def handle_course_event(
    event: Mapping[str, object],
    routing_key: str,
    knowledge: KnowledgeService,
    business: BusinessClient,
    settings: Settings,
) -> None:
    course_value = event.get("courseId") or event.get("course_id") or event.get("id")
    try:
        course_id = int(course_value or 0)
    except (TypeError, ValueError) as error:
        raise ValueError("课程事件缺少有效 courseId") from error
    if course_id <= 0:
        raise ValueError("课程事件缺少有效 courseId")
    if routing_key in {"course.down", "course.expire", "course.delete"}:
        await knowledge.archive_course(course_id)
        return
    if routing_key != "course.up":
        return
    identity = Identity(settings.knowledge_ingestion_user_id, None, f"mq-course-{course_id}")
    course = await business.course_info(identity, course_id)
    title = str(course.get("name") if isinstance(course, dict) else f"课程 {course_id}")
    async with SessionFactory() as session:
        document = await knowledge.create_document(
            session,
            {
                "courseId": course_id,
                "sourceType": "COURSE",
                "sourceId": str(course_id),
                "title": title,
                "content": json.dumps(course, ensure_ascii=False, default=str),
                "visibility": "ENROLLED",
            },
        )
        session.add(IngestionJob(document_id=document.id, requested_by=settings.knowledge_ingestion_user_id))
        await session.commit()


async def _on_message(
    message: AbstractIncomingMessage,
    knowledge: KnowledgeService,
    business: BusinessClient,
    settings: Settings,
) -> None:
    try:
        value = json.loads(message.body.decode("utf-8"))
        if not isinstance(value, dict):
            raise TypeError("课程事件必须是 JSON 对象")
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        logger.error("invalid course event; sending to dead letter queue: %s", error)
        await message.reject(requeue=False)
        return
    try:
        await handle_course_event(value, message.routing_key, knowledge, business, settings)
    except (BusinessUnavailable, OSError, AMQPError):
        await message.nack(requeue=True)
    except Exception:
        logger.exception("course event failed; sending to dead letter queue")
        await message.reject(requeue=False)
    else:
        await message.ack()


async def run_course_event_consumer(
    settings: Settings,
    knowledge: KnowledgeService,
    business: BusinessClient,
    stop: asyncio.Event,
) -> None:
    if not settings.mq_enabled or not settings.rabbitmq_url:
        return
    while not stop.is_set():
        try:
            connection = await aio_pika.connect_robust(settings.rabbitmq_url)
            async with connection:
                channel = await connection.channel()
                exchange = await channel.declare_exchange("course.topic", aio_pika.ExchangeType.TOPIC, durable=True)
                # The legacy agent already owns this DLX as a direct exchange.
                # Reusing its type keeps the Python consumer compatible during
                # the migration and avoids RabbitMQ PRECONDITION_FAILED errors.
                dead_letter = await channel.declare_exchange("agent.knowledge.dlx", aio_pika.ExchangeType.DIRECT, durable=True)
                dead_queue = await channel.declare_queue("agent.course.knowledge.dead", durable=True)
                await dead_queue.bind(dead_letter, routing_key="#")
                queue = await channel.declare_queue(
                    "agent.course.knowledge.queue",
                    durable=True,
                    arguments={"x-dead-letter-exchange": "agent.knowledge.dlx"},
                )
                for key in ("course.up", "course.down", "course.expire", "course.delete"):
                    await queue.bind(exchange, routing_key=key)
                await queue.consume(lambda msg: _on_message(msg, knowledge, business, settings))
                await stop.wait()
        except asyncio.CancelledError:
            raise
        except (AMQPError, OSError, ValueError):
            logger.exception("course event consumer unavailable")
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass
