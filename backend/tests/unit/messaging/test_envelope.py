from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.integrations.messaging.envelope import EventEnvelope, EventEnvelopeError


def envelope(**overrides) -> EventEnvelope:
    values = {
        "schema_version": 1,
        "event_id": uuid4(),
        "aggregate_id": uuid4(),
        "event_type": "download.requested",
        "occurred_at": datetime(2026, 8, 6, 10, tzinfo=UTC),
        "payload": {"job_id": str(uuid4()), "attempt": 0, "version": 0},
    }
    values.update(overrides)
    return EventEnvelope(**values)


def test_envelope_round_trips_as_a_strict_canonical_document() -> None:
    event = envelope()
    encoded = event.to_bytes()
    document = json.loads(encoded)

    assert tuple(sorted(document)) == (
        "aggregate_id",
        "event_id",
        "event_type",
        "occurred_at",
        "payload",
        "schema_version",
    )
    assert document["occurred_at"] == "2026-08-06T10:00:00Z"
    assert EventEnvelope.from_bytes(encoded) == event


@pytest.mark.parametrize(
    "payload",
    [
        {"source_url": "https://media.example/video"},
        {"sourceUrl": "hidden-value"},
        {"nested": {"api_token": "do-not-publish"}},
        {"nested": {"openai_api_key": "do-not-publish"}},
        {"nested": {"openaiApiKey": "do-not-publish"}},
        {"value": "https://media.example/video"},
        {"blob": b"ciphertext"},
    ],
)
def test_envelope_rejects_url_secret_and_binary_payloads(payload) -> None:
    with pytest.raises(EventEnvelopeError):
        envelope(payload=payload)


def test_envelope_rejects_unknown_fields_and_non_utc_time() -> None:
    event = envelope()
    document = json.loads(event.to_bytes())
    document["unexpected"] = True
    with pytest.raises(EventEnvelopeError):
        EventEnvelope.from_bytes(json.dumps(document).encode())
    with pytest.raises(EventEnvelopeError):
        envelope(occurred_at=datetime(2026, 8, 6, 10))


def test_envelope_rejects_unsupported_schema_and_event_type() -> None:
    with pytest.raises(EventEnvelopeError):
        envelope(schema_version=2)
    with pytest.raises(EventEnvelopeError):
        envelope(event_type="Download Requested")


def test_envelope_rejects_duplicate_json_keys() -> None:
    encoded = (
        envelope()
        .to_bytes()
        .replace(
            b'"schema_version":1',
            b'"schema_version":1,"schema_version":1',
        )
    )
    with pytest.raises(EventEnvelopeError):
        EventEnvelope.from_bytes(encoded)
