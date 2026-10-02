"""Strict report publication command contract."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.integrations.messaging.envelope import EventEnvelope, EventEnvelopeError
from app.services.identifiers import AnalysisReportRenderer

_FIELDS = {"job_id", "run_id", "report_id", "renderer_version", "version"}


class ReportMessageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReportRequested:
    job_id: UUID
    run_id: UUID
    report_id: UUID
    renderer_version: str
    version: int


def parse_report_requested(body: bytes) -> ReportRequested:
    try:
        envelope = EventEnvelope.from_bytes(body)
        if (
            envelope.event_type != "analysis.report.publish.requested"
            or set(envelope.payload) != _FIELDS
        ):
            raise ValueError
        job_id = _uuid(envelope.payload["job_id"])
        run_id = _uuid(envelope.payload["run_id"])
        report_id = _uuid(envelope.payload["report_id"])
        renderer = envelope.payload["renderer_version"]
        version = envelope.payload["version"]
        if (
            report_id != envelope.aggregate_id
            or not isinstance(renderer, str)
            or renderer != AnalysisReportRenderer.DEFAULT
            or type(version) is not int
            or version < 0
        ):
            raise ValueError
    except (EventEnvelopeError, TypeError, ValueError) as exc:
        raise ReportMessageError("invalid report publication message") from exc
    return ReportRequested(job_id, run_id, report_id, renderer, version)


def _uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise TypeError
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError
    return parsed
