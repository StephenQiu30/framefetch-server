from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from app.services.analysis.errors import (
    PersistenceActiveRun,
    PersistenceConflict,
    PersistenceIdempotencyConflict,
    PersistenceNotFound,
)
from app.services.analysis.input_models import AnalysisDocumentSnapshot
from app.services.analysis.models import (
    AnalysisArtifactSnapshot,
    AnalysisCreate,
    AnalysisJobSaveResult,
    AnalysisJobSnapshot,
    AnalysisPublish,
    AnalysisRetry,
)
from app.services.analysis.rules.result_types import AnalysisResult


class FakeRepository:
    def __init__(self) -> None:
        self.artifacts: dict[UUID, AnalysisArtifactSnapshot] = {}
        self.documents: dict[UUID, AnalysisDocumentSnapshot] = {}
        self.jobs: dict[UUID, AnalysisJobSnapshot] = {}
        self.commands: list[AnalysisCreate] = []
        self.published: list[AnalysisPublish] = []
        self.results: dict[UUID, AnalysisResult] = {}
        self.outbox_events = 0
        self._keys: dict[tuple[str, str], UUID] = {}
        self._retry_keys: dict[tuple[UUID, str], UUID] = {}

    async def get_artifact_for_download(
        self, download_id: UUID
    ) -> AnalysisArtifactSnapshot | None:
        return next(
            (
                artifact
                for artifact in self.artifacts.values()
                if artifact.download_id == download_id
            ),
            None,
        )

    async def get_document_for_analysis(
        self, document_id: UUID
    ) -> AnalysisDocumentSnapshot | None:
        return self.documents.get(document_id)

    async def create_job_and_enqueue(
        self, command: AnalysisCreate, *, now: datetime
    ) -> AnalysisJobSaveResult:
        self.commands.append(command)
        key = (command.owner_hash, command.idempotency_key)
        existing_id = self._keys.get(key)
        if existing_id is not None:
            existing = self.jobs[existing_id]
            if existing.request_fingerprint != command.request_fingerprint:
                raise PersistenceIdempotencyConflict
            return AnalysisJobSaveResult(existing, created=False)
        snapshot = AnalysisJobSnapshot.queued(command, now=now)
        self.jobs[snapshot.id] = snapshot
        self._keys[key] = snapshot.id
        self.outbox_events += 1
        return AnalysisJobSaveResult(snapshot, created=True)

    async def get_job(self, job_id: UUID) -> AnalysisJobSnapshot | None:
        return self.jobs.get(job_id)

    async def get_latest_job_for_download(
        self, download_id: UUID, owner_hash: str
    ) -> AnalysisJobSnapshot | None:
        matches = [
            job
            for job in self.jobs.values()
            if job.owner_hash == owner_hash
            and job.artifact_id is not None
            and self.artifacts[job.artifact_id].download_id == download_id
        ]
        return max(matches, key=lambda job: job.created_at, default=None)

    async def get_latest_job_for_document(
        self, document_id: UUID, owner_hash: str
    ) -> AnalysisJobSnapshot | None:
        matches = [
            job
            for job in self.jobs.values()
            if job.owner_hash == owner_hash and job.document_id == document_id
        ]
        return max(matches, key=lambda job: job.created_at, default=None)

    async def get_result(self, job_id: UUID) -> AnalysisResult | None:
        return self.results.get(job_id)

    async def get_latest_report(self, job_id: UUID):
        return None

    async def get_current_report_file(self, job_id: UUID, report_format: str):
        return None

    async def retry_job_and_enqueue(
        self, command: AnalysisRetry, *, now: datetime
    ) -> AnalysisJobSaveResult:
        current = self.jobs.get(command.job_id)
        if current is None or current.owner_hash != command.owner_hash:
            raise PersistenceNotFound
        key = (command.job_id, command.idempotency_key)
        existing = self._retry_keys.get(key)
        if existing is not None:
            return AnalysisJobSaveResult(current, created=False)
        if current.status not in {"failed", "cancelled", "succeeded"}:
            raise PersistenceActiveRun
        retried = replace(
            current,
            status="queued",
            stage=None,
            progress=0,
            attempt=0,
            version=current.version + 1,
            run_id=command.run_id,
            run_no=current.run_no + 1,
            run_trigger=command.trigger,
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
            started_at=None,
            retry_at=None,
            finished_at=None,
            error_code=None,
            updated_at=now,
        )
        self.jobs[command.job_id] = retried
        self._retry_keys[key] = command.run_id
        self.outbox_events += 1
        return AnalysisJobSaveResult(retried, created=True)

    async def cancel_job(
        self, job_id: UUID, owner_hash: str, now: datetime
    ) -> AnalysisJobSnapshot:
        current = self.jobs.get(job_id)
        if current is None or current.owner_hash != owner_hash:
            raise PersistenceNotFound
        if current.status not in {"queued", "running", "retry_wait", "cancelled"}:
            raise PersistenceConflict
        if current.status == "cancelled":
            return current
        cancelled = replace(
            current,
            status="cancelled",
            stage=None,
            error_code="cancelled",
            finished_at=now,
            updated_at=now,
        )
        self.jobs[job_id] = cancelled
        return cancelled

    async def delete_job(self, job_id: UUID, owner_hash: str, now: datetime) -> bool:
        current = self.jobs.get(job_id)
        if current is None or current.owner_hash != owner_hash:
            raise PersistenceNotFound
        del self.jobs[job_id]
        return True

    async def publish_result(self, command: AnalysisPublish) -> AnalysisJobSnapshot:
        self.published.append(command)
        current = self.jobs[command.job_id]
        updated = replace(
            current,
            status="succeeded",
            stage=None,
            progress=100,
            version=current.version + 1,
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
            finished_at=command.now,
            updated_at=command.now,
        )
        self.jobs[command.job_id] = updated
        return updated


def published_result(repository: FakeRepository) -> AnalysisResult:
    return repository.published[-1].result
