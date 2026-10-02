from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.integrations.messaging.envelope import EventEnvelope
from app.workers.download.message import DownloadMessageError, parse_download_requested


def envelope(**payload) -> EventEnvelope:
    job_id = uuid4()
    return EventEnvelope(
        schema_version=1,
        event_id=uuid4(),
        aggregate_id=job_id,
        event_type="download.requested",
        occurred_at=datetime.now(UTC),
        payload={"job_id": str(job_id), "attempt": 0, "version": 1, **payload},
    )


def test_parse_strict_download_request() -> None:
    message = envelope()
    parsed = parse_download_requested(message.to_bytes())
    assert parsed.job_id == message.aggregate_id
    assert (parsed.attempt, parsed.version) == (0, 1)


@pytest.mark.parametrize(
    "change",
    [
        {"job_id": str(uuid4())},
        {"attempt": -1},
        {"attempt": True},
        {"extra": 1},
    ],
)
def test_parse_rejects_malformed_or_mismatched_payload(change) -> None:
    with pytest.raises(DownloadMessageError):
        parse_download_requested(envelope(**change).to_bytes())
