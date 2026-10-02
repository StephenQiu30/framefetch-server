from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.integrations.messaging.envelope import EventEnvelope, EventEnvelopeError
from app.services.imports.events import CONTENT_IMPORT_VERIFY_REQUESTED
from app.services.imports.rules.enums import ContentKind

_FIELDS = {"resource_id", "content_kind", "attempt", "version"}


class ImportMessageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ImportVerifyRequested:
    resource_id: UUID
    content_kind: ContentKind
    attempt: int
    version: int


def parse_import_verify_requested(body: bytes) -> ImportVerifyRequested:
    try:
        envelope = EventEnvelope.from_bytes(body)
    except EventEnvelopeError as error:
        raise ImportMessageError("invalid event envelope") from error
    if (
        envelope.event_type != CONTENT_IMPORT_VERIFY_REQUESTED
        or set(envelope.payload) != _FIELDS
    ):
        raise ImportMessageError("import payload fields do not match schema")
    try:
        resource_id = _uuid(envelope.payload["resource_id"])
        raw_kind = envelope.payload["content_kind"]
        if not isinstance(raw_kind, str):
            raise TypeError
        content_kind = ContentKind(raw_kind)
        attempt = _integer(envelope.payload["attempt"], positive=True)
        version = _integer(envelope.payload["version"])
    except (TypeError, ValueError) as error:
        raise ImportMessageError("import payload values are invalid") from error
    if resource_id != envelope.aggregate_id:
        raise ImportMessageError("import payload values are invalid")
    return ImportVerifyRequested(resource_id, content_kind, attempt, version)


def _uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise TypeError
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError
    return parsed


def _integer(value: object, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError
    return value
