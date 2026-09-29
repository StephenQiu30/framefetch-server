from __future__ import annotations

import argparse
import asyncio
import os
from datetime import UTC, datetime

import aio_pika
from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.integrations.messaging import (
    RabbitMqPublisher,
    RabbitMqTopology,
    configured_rabbitmq_url,
)
from app.workers.dlq.repository import DlqReplayRepository
from app.workers.dlq.service import ALLOWED_EVENTS, DlqReplayService


async def run(queue_name: str, actor: str, reason: str) -> None:
    settings = Settings(service_role="worker")
    url = os.environ.get("RABBITMQ_DLQ_URL")
    if not url:
        raise RuntimeError("RABBITMQ_DLQ_URL is required")
    topology = RabbitMqTopology(
        settings.rabbitmq_exchange,
        settings.download_queue,
        settings.download_routing_key,
        report_queue=settings.analysis_report_queue,
        report_routing_key=settings.analysis_report_routing_key,
    )
    engine = create_engine(settings.database_url)
    publisher = RabbitMqPublisher(
        url,
        topology,
        connection_timeout=settings.rabbitmq_connection_timeout_seconds,
        publish_timeout=settings.rabbitmq_publish_timeout_seconds,
        heartbeat=settings.rabbitmq_heartbeat_seconds,
        reconnect_interval=settings.rabbitmq_reconnect_interval_seconds,
        connection_name="video-server-dlq-replay",
        app_id="video-server-dlq-replay",
    )
    connection = await aio_pika.connect_robust(
        configured_rabbitmq_url(
            url,
            heartbeat=settings.rabbitmq_heartbeat_seconds,
            reconnect_interval=settings.rabbitmq_reconnect_interval_seconds,
            connection_name="video-server-dlq-reader",
        ),
        timeout=settings.rabbitmq_connection_timeout_seconds,
    )
    try:
        channel = await connection.channel()
        queue = await channel.declare_queue(queue_name, passive=True)
        message = await queue.get(fail=False)
        if message is None:
            raise RuntimeError("selected DLQ is empty")
        await publisher.start()
        service = DlqReplayService(
            DlqReplayRepository(create_session_factory(engine)),
            publisher,
            lambda: datetime.now(UTC),
        )
        audit = await service.replay(
            message, source_queue=queue_name, actor=actor, reason=reason
        )
        print(f"replayed audit_id={audit.id} event_id={audit.replay_event_id}")
    finally:
        await publisher.close()
        await connection.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay one audited RabbitMQ DLQ event"
    )
    parser.add_argument("--queue", required=True, choices=tuple(ALLOWED_EVENTS))
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    if not 1 <= len(args.actor.strip()) <= 128:
        parser.error("actor must contain 1-128 characters")
    if not 1 <= len(args.reason.strip()) <= 256:
        parser.error("reason must contain 1-256 characters")
    asyncio.run(run(args.queue, args.actor.strip(), args.reason.strip()))


if __name__ == "__main__":
    main()
