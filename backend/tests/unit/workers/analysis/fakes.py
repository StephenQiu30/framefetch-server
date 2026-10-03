from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.services.analysis.models import AnalysisJobSnapshot
from app.services.analysis.rules.result_types import AnalysisResult
from app.services.analysis_execution.errors import AnalysisPersistenceRejected
from app.services.analysis_execution.models import (
    AnalysisArtifactSource,
    AnalysisExecutionSettings,
    AnalysisStepBegin,
    AnalysisStepStatus,
    LocalAnalysisArtifact,
)

NOW = datetime(2026, 8, 6, 12, tzinfo=UTC)


def running_job() -> AnalysisJobSnapshot:
    run_id = uuid4()
    return AnalysisJobSnapshot(
        id=uuid4(),
        artifact_id=uuid4(),
        owner_hash="a" * 64,
        request_fingerprint="b" * 64,
        input_sha256="c" * 64,
        skill_id="director-breakdown",
        skill_instructions="导演拉片完整指令",
        skill_instructions_sha256=hashlib.sha256(
            "导演拉片完整指令".encode()
        ).hexdigest(),
        output_language="zh-CN",
        custom_prompt=None,
        status="running",
        stage="preparing",
        progress=0,
        attempt=1,
        max_attempts=3,
        version=1,
        run_id=run_id,
        run_no=1,
        run_trigger="initial",
        lease_owner="analysis-worker",
        lease_expires_at=NOW + timedelta(minutes=5),
        heartbeat_at=NOW,
        started_at=NOW,
        retry_at=None,
        finished_at=None,
        error_code=None,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeRepository:
    def __init__(self, job: AnalysisJobSnapshot) -> None:
        self.job = job
        self.heartbeats: list[tuple[str, int]] = []
        self.failures: list[dict[str, object]] = []
        self.published: list[AnalysisResult] = []
        self.source_error: Exception | None = None
        self.publish_error: Exception | None = None
        self.heartbeat_failure_stage: str | None = None
        # Owner-visible heartbeats in that stage before cancellation is observed.
        self.heartbeat_failure_after = 2
        self._stage_counts: dict[str, int] = {}
        self.claims: list[str] = []
        self.steps: dict[str, tuple[str, str, object | None]] = {}

    async def claim_run(
        self,
        job_id: UUID,
        run_id: UUID,
        run_no: int,
        owner: str,
        now: datetime,
        lease_for: timedelta,
    ) -> AnalysisJobSnapshot | None:
        if (job_id, run_id, run_no) != (self.job.id, self.job.run_id, self.job.run_no):
            return None
        self.claims.append(owner)
        self.job = replace(self.job, lease_owner=owner)
        return self.job

    async def get_job(self, job_id: UUID) -> AnalysisJobSnapshot | None:
        return self.job if job_id == self.job.id else None

    async def get_artifact_source(
        self, job: AnalysisJobSnapshot, now: datetime
    ) -> AnalysisArtifactSource:
        if self.source_error is not None:
            raise self.source_error
        return AnalysisArtifactSource(
            job.artifact_id,
            "video-artifacts",
            f"downloads/{job.id}/1/video.mp4",
            job.input_sha256,
            5,
            2_000,
            "mp4",
        )

    async def heartbeat(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        *,
        stage: str,
        progress: int,
        now: datetime,
        lease_for: timedelta,
    ) -> bool:
        self.heartbeats.append((stage, progress))
        count = self._stage_counts.get(stage, 0) + 1
        self._stage_counts[stage] = count
        if (
            self.heartbeat_failure_stage == stage
            and count > self.heartbeat_failure_after
        ):
            self.job = replace(
                self.job,
                status="cancelled",
                stage=None,
                lease_owner=None,
                lease_expires_at=None,
            )
            return False
        self.job = replace(
            self.job,
            stage=stage,
            progress=progress,
            version=self.job.version + 1,
            lease_expires_at=now + lease_for,
        )
        return True

    async def publish_result(
        self,
        job_id: UUID,
        run_id: UUID,
        worker_id: str,
        expected_version: int,
        result: AnalysisResult,
        provider: str,
        model: str,
        cli_version: str,
        now: datetime,
    ) -> None:
        if self.publish_error is not None:
            raise self.publish_error
        assert run_id == self.job.run_id
        assert expected_version == self.job.version
        assert (provider, model, cli_version) == (
            "controlled",
            "controlled",
            "controlled",
        )
        self.published.append(result)
        self.job = replace(self.job, status="succeeded", stage=None)

    async def complete_failure(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        **values: object,
    ) -> AnalysisJobSnapshot:
        self.failures.append(values)
        status = "retry_wait" if values["retryable"] else "failed"
        self.job = replace(self.job, status=status, stage=None)
        return self.job

    async def begin_step(
        self, run_id: UUID, step_key: str, input_sha256: str, *, now: datetime
    ) -> AnalysisStepBegin:
        current = self.steps.get(step_key)
        if current is None:
            self.steps[step_key] = ("started", input_sha256, None)
            return AnalysisStepBegin(AnalysisStepStatus.NEW)
        if current[1] != input_sha256:
            raise AnalysisPersistenceRejected("analysis step input changed")
        if current[0] == "failed":
            return AnalysisStepBegin(AnalysisStepStatus.FAILED, current[2])
        if current[0] == "succeeded":
            return AnalysisStepBegin(AnalysisStepStatus.REPLAY, current[2])
        return AnalysisStepBegin(AnalysisStepStatus.UNKNOWN)

    async def complete_step(
        self, run_id: UUID, step_key: str, payload: object, *, now: datetime
    ) -> None:
        status, digest, _ = self.steps[step_key]
        assert status == "started"
        self.steps[step_key] = ("succeeded", digest, payload)

    async def abandon_step(self, run_id: UUID, step_key: str) -> None:
        if self.steps.get(step_key, ("",))[0] == "started":
            del self.steps[step_key]

    async def fail_step(
        self, run_id: UUID, step_key: str, error_code: str, *, now: datetime
    ) -> None:
        status, digest, _ = self.steps[step_key]
        assert status == "started"
        self.steps[step_key] = ("failed", digest, error_code)


class FakeLoader:
    def __init__(self, root: Path) -> None:
        self.local = LocalAnalysisArtifact(root, root / "source.mp4")
        self.cleaned = False

    async def materialize(
        self, source: AnalysisArtifactSource, *, job_id: UUID, attempt: int
    ) -> LocalAnalysisArtifact:
        return self.local

    async def cleanup(self, local: LocalAnalysisArtifact) -> None:
        self.cleaned = True


def settings() -> AnalysisExecutionSettings:
    return AnalysisExecutionSettings(
        bucket="video-artifacts",
        lease_for=timedelta(seconds=30),
        heartbeat_interval=0.01,
        max_source_bytes=1024,
    )
