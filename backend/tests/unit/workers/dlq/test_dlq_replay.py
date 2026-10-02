from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from app.integrations.messaging.envelope import EventEnvelope, EventEnvelopeError
from app.workers.dlq.repository import ReplayAudit
from app.workers.dlq.service import ALLOWED_EVENTS, DlqReplayService

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)
ORIGINAL_ID = UUID("11111111-1111-4111-8111-111111111111")
REPLAY_ID = UUID("22222222-2222-4222-8222-222222222222")
AUDIT_ID = UUID("33333333-3333-4333-8333-333333333333")


def test_all_declared_dead_letter_queues_can_be_replayed() -> None:
    assert ALLOWED_EVENTS["video.import.dead"] == "content.import.verify.requested"
    # Skill runs are Temporal workflows; there is no analysis queue to replay into.
    assert "video.analysis.dead" not in ALLOWED_EVENTS


class FakeDelivery:
    def __init__(self, *, replay_count: int = 0) -> None:
        self.body = EventEnvelope(
            1,
            ORIGINAL_ID,
            UUID("44444444-4444-4444-8444-444444444444"),
            "analysis.report.publish.requested",
            NOW,
            {
                "job_id": "55555555-5555-4555-8555-555555555555",
                "run_id": "66666666-6666-4666-8666-666666666666",
                "report_id": "77777777-7777-4777-8777-777777777777",
                "renderer_version": "markdown-docx-v1",
                "version": 1,
            },
        ).to_bytes()
        self.headers = {"x-replay-count": replay_count}
        self.acked = False
        self.requeued = False

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, *, requeue: bool) -> None:
        self.requeued = requeue


class FakeRepository:
    def __init__(self) -> None:
        self.audit = ReplayAudit(AUDIT_ID, REPLAY_ID, "pending", NOW)
        self.published = False
        self.failed = False

    async def get_or_create(self, **values: object) -> ReplayAudit:
        assert values["actor"] == "operator@example.com"
        assert values["reason"] == "validated model fix"
        return self.audit

    async def mark_published(self, audit_id, now: datetime) -> None:
        assert audit_id == AUDIT_ID
        self.published = True

    async def mark_failed(self, audit_id, code: str, now: datetime) -> None:
        self.failed = True


class FakePublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[tuple[EventEnvelope, object]] = []

    async def publish(self, envelope, *, headers=None) -> None:
        if self.fail:
            raise RuntimeError("broker down")
        self.messages.append((envelope, headers))


@pytest.mark.asyncio
async def test_replay_creates_new_event_and_acknowledges_after_audit() -> None:
    delivery = FakeDelivery()
    repository = FakeRepository()
    publisher = FakePublisher()

    audit = await DlqReplayService(repository, publisher, lambda: NOW).replay(
        delivery,
        source_queue="video.analysis-report.dead",
        actor="operator@example.com",
        reason="validated model fix",
    )

    assert audit.replay_event_id == REPLAY_ID
    assert repository.published and delivery.acked and not delivery.requeued
    replay, headers = publisher.messages[0]
    assert replay.event_id == REPLAY_ID and replay.payload["version"] == 1
    assert headers == {
        "x-replay-count": 1,
        "x-original-event-id": str(ORIGINAL_ID),
    }


@pytest.mark.asyncio
async def test_replay_failure_and_limit_keep_original_in_dlq() -> None:
    failed = FakeDelivery()
    repository = FakeRepository()
    with pytest.raises(RuntimeError):
        await DlqReplayService(
            repository, FakePublisher(fail=True), lambda: NOW
        ).replay(
            failed,
            source_queue="video.analysis-report.dead",
            actor="operator@example.com",
            reason="validated model fix",
        )
    assert repository.failed and failed.requeued and not failed.acked

    limited = FakeDelivery(replay_count=3)
    with pytest.raises(EventEnvelopeError):
        await DlqReplayService(repository, FakePublisher(), lambda: NOW).replay(
            limited,
            source_queue="video.analysis-report.dead",
            actor="operator@example.com",
            reason="validated model fix",
        )
    assert limited.requeued and not limited.acked
