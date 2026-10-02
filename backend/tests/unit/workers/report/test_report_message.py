from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.integrations.messaging.envelope import EventEnvelope
from app.workers.report.message import ReportMessageError, parse_report_requested


def test_report_message_is_strict_and_contains_only_stable_ids() -> None:
    job_id, run_id, report_id = uuid4(), uuid4(), uuid4()
    body = EventEnvelope(
        schema_version=1,
        event_id=uuid4(),
        aggregate_id=report_id,
        event_type="analysis.report.publish.requested",
        occurred_at=datetime(2026, 8, 10, tzinfo=UTC),
        payload={
            "job_id": str(job_id),
            "run_id": str(run_id),
            "report_id": str(report_id),
            "renderer_version": "analysis-report",
            "version": 4,
        },
    ).to_bytes()

    requested = parse_report_requested(body)
    assert (requested.job_id, requested.run_id, requested.report_id) == (
        job_id,
        run_id,
        report_id,
    )
    with pytest.raises(ReportMessageError):
        parse_report_requested(b"not-json")
