from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.integrations.messaging.envelope import EventEnvelope
from app.services.imports.events import (
    CONTENT_IMPORT_VERIFY_REQUESTED,
    import_verify_requested_payload,
)
from app.services.imports.rules.enums import ContentKind
from app.workers.imports.message import (
    ImportMessageError,
    parse_import_verify_requested,
)

NOW = datetime(2026, 8, 14, tzinfo=UTC)
RESOURCE_ID = UUID("11111111-1111-4111-8111-111111111111")


def envelope(**changes: object) -> EventEnvelope:
    payload: dict[str, object] = import_verify_requested_payload(
        RESOURCE_ID, ContentKind.VIDEO, 1, 3
    )
    payload.update(changes)
    return EventEnvelope(
        schema_version=1,
        event_id=uuid4(),
        aggregate_id=RESOURCE_ID,
        event_type=CONTENT_IMPORT_VERIFY_REQUESTED,
        occurred_at=NOW,
        payload=payload,  # type: ignore[arg-type]
    )


def test_parse_strict_import_verification_request() -> None:
    parsed = parse_import_verify_requested(envelope().to_bytes())

    assert parsed.resource_id == RESOURCE_ID
    assert parsed.content_kind is ContentKind.VIDEO
    assert (parsed.attempt, parsed.version) == (1, 3)


@pytest.mark.parametrize(
    "change",
    (
        {"resource_id": str(uuid4())},
        {"content_kind": "generic_document"},
        {"attempt": 0},
        {"attempt": True},
        {"version": -1},
        {"extra": "not-allowed"},
    ),
)
def test_parse_rejects_malformed_or_mismatched_import_payload(
    change: dict[str, object],
) -> None:
    with pytest.raises(ImportMessageError):
        parse_import_verify_requested(envelope(**change).to_bytes())


def test_import_payload_rejects_invalid_attempt_and_version() -> None:
    with pytest.raises(ValueError, match="attempt"):
        import_verify_requested_payload(RESOURCE_ID, ContentKind.VIDEO, 0, 0)
    with pytest.raises(ValueError, match="version"):
        import_verify_requested_payload(RESOURCE_ID, ContentKind.VIDEO, 1, -1)
