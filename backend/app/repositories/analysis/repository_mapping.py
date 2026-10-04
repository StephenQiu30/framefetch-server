"""Map mutable analysis rows into application-owned snapshots."""

from copy import deepcopy

from app.core.db import as_utc
from app.models import AnalysisJobRow, AnalysisRunRow, ArtifactRow, DownloadJobRow
from app.services.analysis.models import AnalysisArtifactSnapshot, AnalysisJobSnapshot
from app.services.analysis.rules.content_document import ContentSourceSet


def analysis_job_snapshot(
    row: AnalysisJobRow, run: AnalysisRunRow | None = None
) -> AnalysisJobSnapshot:
    run_id = run.id if run is not None else row.active_run_id
    run_no = run.run_no if run is not None else row.current_run_no
    run_trigger = run.trigger if run is not None else row.current_run_trigger
    return AnalysisJobSnapshot(
        id=row.id,
        skill_inputs=deepcopy(row.skill_inputs),
        content_source=None
        if row.content_source is None
        else ContentSourceSet.model_validate(row.content_source),
        artifact_id=row.artifact_id,
        owner_hash=row.owner_hash,
        request_fingerprint=row.request_fingerprint,
        input_sha256=row.input_sha256,
        skill_id=row.skill_id,
        skill_instructions=row.skill_instructions,
        skill_instructions_sha256=row.skill_instructions_sha256,
        output_language=row.output_language,
        custom_prompt=row.custom_prompt,
        status=row.status,
        stage=row.stage,
        progress=row.progress,
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        version=row.version,
        run_id=run_id,
        run_no=run_no,
        run_trigger=run_trigger,
        current_report_id=row.current_report_id,
        lease_owner=row.lease_owner,
        lease_expires_at=None
        if row.lease_expires_at is None
        else as_utc(row.lease_expires_at),
        heartbeat_at=None if row.heartbeat_at is None else as_utc(row.heartbeat_at),
        started_at=None if row.started_at is None else as_utc(row.started_at),
        retry_at=None if row.retry_at is None else as_utc(row.retry_at),
        finished_at=None if row.finished_at is None else as_utc(row.finished_at),
        error_code=row.error_code,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
        document_id=row.document_id,
        input_kind=row.input_kind,
        result_contract=row.result_contract,
    )


def analysis_artifact_snapshot(
    artifact: ArtifactRow, download: DownloadJobRow
) -> AnalysisArtifactSnapshot:
    return AnalysisArtifactSnapshot(
        id=artifact.id,
        download_id=download.id,
        owner_hash=download.owner_hash,
        download_status=download.status,
        sha256=artifact.sha256,
    )
