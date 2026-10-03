from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.services.analysis.rules.content_document import ContentSourceSet
from app.services.analysis.rules.enums import (
    AnalysisErrorCode,
    AnalysisInputKind,
    AnalysisReportStatus,
    AnalysisResultContract,
    AnalysisStage,
    AnalysisStatus,
)
from app.services.analysis.rules.result_types import AnalysisResult
from app.services.quotas import UserQuota


@dataclass(frozen=True, slots=True)
class AnalysisArtifactSnapshot:
    id: UUID
    download_id: UUID
    owner_hash: str
    download_status: str
    sha256: str


@dataclass(frozen=True, slots=True)
class AnalysisCreate:
    id: UUID
    run_id: UUID
    artifact_id: UUID | None
    owner_hash: str
    idempotency_key: str
    request_fingerprint: str
    input_sha256: str
    skill_id: str
    skill_instructions: str
    skill_instructions_sha256: str
    output_language: str
    custom_prompt: str | None
    max_attempts: int
    outbox_event_id: UUID
    outbox_event_type: str
    document_id: UUID | None = None
    input_kind: AnalysisInputKind = AnalysisInputKind.VIDEO
    result_contract: AnalysisResultContract = (
        AnalysisResultContract.VIDEO_VISUAL_ANALYSIS
    )
    quota: UserQuota = UserQuota()
    content_source: ContentSourceSet | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class AnalysisJobSnapshot:
    id: UUID
    artifact_id: UUID | None
    owner_hash: str
    request_fingerprint: str
    input_sha256: str
    skill_id: str
    skill_instructions: str
    skill_instructions_sha256: str
    output_language: str
    custom_prompt: str | None
    status: str
    stage: str | None
    progress: int
    attempt: int
    max_attempts: int
    version: int
    run_id: UUID
    run_no: int
    run_trigger: str
    lease_owner: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    started_at: datetime | None
    retry_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    current_report_id: UUID | None = None
    document_id: UUID | None = None
    input_kind: str = AnalysisInputKind.VIDEO.value
    result_contract: str = AnalysisResultContract.VIDEO_VISUAL_ANALYSIS.value

    content_source: ContentSourceSet | None = field(default=None, repr=False)

    @classmethod
    def queued(cls, command: AnalysisCreate, *, now: datetime) -> AnalysisJobSnapshot:
        return cls(
            id=command.id,
            artifact_id=command.artifact_id,
            owner_hash=command.owner_hash,
            request_fingerprint=command.request_fingerprint,
            input_sha256=command.input_sha256,
            skill_id=command.skill_id,
            skill_instructions=command.skill_instructions,
            skill_instructions_sha256=command.skill_instructions_sha256,
            output_language=command.output_language,
            custom_prompt=command.custom_prompt,
            status=AnalysisStatus.QUEUED.value,
            stage=None,
            progress=0,
            attempt=0,
            max_attempts=command.max_attempts,
            version=0,
            run_id=command.run_id,
            run_no=1,
            run_trigger="initial",
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
            started_at=None,
            retry_at=None,
            finished_at=None,
            error_code=None,
            created_at=now,
            updated_at=now,
            document_id=command.document_id,
            input_kind=command.input_kind.value,
            result_contract=command.result_contract.value,
            content_source=command.content_source,
        )


@dataclass(frozen=True, slots=True)
class AnalysisJobSaveResult:
    job: AnalysisJobSnapshot
    created: bool


@dataclass(frozen=True, slots=True)
class AnalysisRetry:
    job_id: UUID
    run_id: UUID
    owner_hash: str
    idempotency_key: str
    trigger: str
    outbox_event_id: UUID
    max_attempts: int
    max_runs_per_job: int = 10
    min_interval_seconds: int = 0
    retries_per_day: int = 20
    quota: UserQuota = UserQuota()


@dataclass(frozen=True, slots=True)
class AnalysisPublish:
    job_id: UUID
    run_id: UUID
    result: AnalysisResult
    lease_owner: str
    expected_version: int
    provider: str
    model: str
    cli_version: str
    now: datetime


@dataclass(frozen=True, slots=True)
class AnalysisJobView:
    id: UUID
    run_id: UUID
    run_no: int
    run_trigger: str
    version: int
    skill_id: str
    output_language: str
    status: AnalysisStatus
    stage: AnalysisStage | None
    progress: int
    attempt: int
    error_code: AnalysisErrorCode | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    result: AnalysisResult | None
    report: AnalysisReportSnapshot | None = None
    current_report_id: UUID | None = None
    input_kind: AnalysisInputKind = AnalysisInputKind.VIDEO
    result_contract: AnalysisResultContract = (
        AnalysisResultContract.VIDEO_VISUAL_ANALYSIS
    )


@dataclass(frozen=True, slots=True)
class AnalysisReportArtifactSnapshot:
    format: str
    object_key: str
    media_type: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class AnalysisReportSnapshot:
    id: UUID
    job_id: UUID
    run_id: UUID
    status: AnalysisReportStatus
    markdown: str
    content_sha256: str
    renderer_version: str
    created_at: datetime
    published_at: datetime | None
    artifacts: tuple[AnalysisReportArtifactSnapshot, ...]


@dataclass(frozen=True, slots=True)
class AnalysisReportFile:
    content: bytes
    filename: str
    media_type: str


@dataclass(frozen=True, slots=True)
class AnalysisStoredReportFile:
    object_key: str
    media_type: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class AnalysisSkillView:
    id: str
    display_name: str
    description: str
    default_prompt: str
    input_kinds: tuple[AnalysisInputKind, ...]
    result_contract: AnalysisResultContract


@dataclass(frozen=True, slots=True)
class AnalysisSkillResolution:
    view: AnalysisSkillView
    instructions: str
    instructions_sha256: str
