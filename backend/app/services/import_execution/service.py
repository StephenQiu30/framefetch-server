from __future__ import annotations

import asyncio
import logging
import re
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.services.import_execution.errors import (
    ImportExecutionUnavailable,
    ImportLeaseLost,
    ImportVerificationRejected,
)
from app.services.import_execution.models import (
    ImportExecutionSettings,
    ImportVerificationClaim,
)
from app.services.import_execution.monitor import monitored
from app.services.import_execution.ports import (
    Clock,
    ImportExecutionRepository,
    ImportExecutionStorage,
    ImportThumbnailRecovery,
    ImportWorkspaceManager,
    VideoImportVerifier,
)
from app.services.imports.models import ImportDisposition
from app.services.imports.rules.enums import (
    ContentKind,
    ImportErrorCode,
    ImportSourceFormat,
)

_log = logging.getLogger(__name__)
_ARTIFACT_KEY = re.compile(
    r"downloads/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}/[1-9][0-9]*/video\.(?:mp4|webm)"
)


class ImportExecution:
    def __init__(
        self,
        *,
        repository: ImportExecutionRepository,
        storage: ImportExecutionStorage,
        workspace: ImportWorkspaceManager,
        video_verifier: VideoImportVerifier,
        clock: Clock,
        settings: ImportExecutionSettings,
        thumbnail_recovery: ImportThumbnailRecovery | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._workspace = workspace
        self._video_verifier = video_verifier
        self._clock = clock
        self._settings = settings
        self._thumbnail_recovery = thumbnail_recovery

    async def execute(
        self,
        resource_id: UUID,
        content_kind: ContentKind,
        attempt: int,
        expected_version: int,
    ) -> ImportDisposition:
        if content_kind is not ContentKind.VIDEO:
            return ImportDisposition.RETRY
        try:
            claim = await self._repository.claim_verification(
                resource_id,
                content_kind,
                attempt,
                expected_version,
                worker_id=self._settings.worker_id,
                now=self._clock(),
                lease_for=self._settings.lease_for,
            )
        except Exception:
            return ImportDisposition.RETRY
        if claim is None:
            return ImportDisposition.ACK
        return await self._execute_claimed(claim)

    async def _execute_claimed(
        self, claim: ImportVerificationClaim
    ) -> ImportDisposition:
        task_id = f"import_{claim.resource_id.hex}_{claim.attempt}"
        workspace_path: Path | None = None
        try:
            try:
                workspace = await self._workspace.create(task_id)
                workspace_path = workspace.path
                await monitored(
                    lambda: self._storage.download(
                        claim.object_key, workspace.input_path
                    ),
                    lambda: self._heartbeat(claim, stage="verifying", progress=60),
                    interval=self._settings.heartbeat_interval,
                )
                artifact = await monitored(
                    lambda: self._video_verifier(workspace.input_path, claim),
                    lambda: self._heartbeat(claim, stage="verifying", progress=75),
                    interval=self._settings.heartbeat_interval,
                )
                if self._thumbnail_recovery is not None and claim.owner_hash:
                    await self._thumbnail_recovery.recover(
                        claim.resource_id,
                        claim.owner_hash,
                        workspace.input_path,
                    )
                final_key = _artifact_object_key(claim)
                await monitored(
                    lambda: self._storage.promote(
                        claim.object_key,
                        final_key,
                        expected_size_bytes=artifact.size_bytes,
                        sha256=artifact.sha256,
                        content_type=artifact.content_type,
                    ),
                    lambda: self._heartbeat(claim, stage="uploading", progress=95),
                    interval=self._settings.heartbeat_interval,
                )
                now = self._clock()
                await self._repository.complete_verification(
                    claim,
                    artifact,
                    worker_id=self._settings.worker_id,
                    bucket=self._settings.bucket,
                    now=now,
                )
            except asyncio.CancelledError:
                raise
            except ImportLeaseLost:
                return ImportDisposition.ACK
            except ImportExecutionUnavailable:
                return ImportDisposition.RETRY
            except ImportVerificationRejected as exc:
                try:
                    await self._repository.fail_verification(
                        claim,
                        exc.code,
                        worker_id=self._settings.worker_id,
                        now=self._clock(),
                    )
                except Exception:
                    return ImportDisposition.RETRY
                with suppress(Exception):
                    await self._storage.delete(claim.object_key)
                return ImportDisposition.ACK
            except Exception:
                return ImportDisposition.RETRY
            with suppress(Exception):
                await self._storage.delete(claim.object_key)
            return ImportDisposition.ACK
        finally:
            with suppress(Exception):
                await self._workspace.cleanup(task_id, workspace_path)

    async def _heartbeat(
        self, claim: ImportVerificationClaim, *, stage: str, progress: int
    ) -> None:
        try:
            owned = await self._repository.heartbeat_verification(
                claim.resource_id,
                claim.attempt,
                worker_id=self._settings.worker_id,
                stage=stage,
                progress=progress,
                now=self._clock(),
                lease_for=self._settings.lease_for,
            )
        except Exception as exc:
            raise ImportExecutionUnavailable from exc
        if not owned:
            raise ImportLeaseLost


class ImportRecoverySweeper:
    def __init__(
        self,
        repository: ImportExecutionRepository,
        storage: ImportExecutionStorage,
        workspace: ImportWorkspaceManager,
        clock: Clock,
        *,
        interval: float,
        batch_size: int,
        workspace_grace: timedelta,
        artifact_orphan_grace: timedelta,
        delete_timeout: float,
    ) -> None:
        if interval <= 0 or not 1 <= batch_size <= 200:
            raise ValueError("invalid import recovery settings")
        if (
            workspace_grace.total_seconds() <= 0
            or artifact_orphan_grace.total_seconds() <= 0
            or delete_timeout <= 0
        ):
            raise ValueError("import cleanup bounds must be positive")
        self._repository = repository
        self._storage = storage
        self._workspace = workspace
        self._clock = clock
        self._interval = interval
        self._batch_size = batch_size
        self._workspace_grace = workspace_grace
        self._artifact_orphan_grace = artifact_orphan_grace
        self._delete_timeout = delete_timeout

    async def tick(self) -> tuple[UUID, ...]:
        now = self._clock()
        recovered = await self._repository.recover_expired_verifications(
            now, limit=self._batch_size
        )
        await self._workspace.cleanup_orphans(
            now, older_than=self._workspace_grace, limit=self._batch_size
        )
        await self._cleanup_artifact_orphans(now)
        return recovered

    async def _cleanup_artifact_orphans(self, now: datetime) -> None:
        expected = await self._repository.expected_artifact_object_keys()
        cutoff = now - self._artifact_orphan_grace
        deleted = 0
        for item in await self._storage.list("downloads/"):
            if deleted >= self._batch_size:
                break
            if (
                item.object_key in expected
                or _ARTIFACT_KEY.fullmatch(item.object_key) is None
                or item.last_modified > cutoff
            ):
                continue
            await asyncio.wait_for(
                self._storage.delete(item.object_key), timeout=self._delete_timeout
            )
            deleted += 1

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:
                _log.exception("media import recovery sweep failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._interval)
            except TimeoutError:
                pass


def _artifact_object_key(claim: ImportVerificationClaim) -> str:
    if (
        claim.content_kind is not ContentKind.VIDEO
        or claim.source_format is not ImportSourceFormat.MP4
        or claim.attempt < 1
    ):
        raise ImportVerificationRejected(
            ImportErrorCode.VIDEO_INVALID, "unsupported import artifact identity"
        )
    return f"downloads/{claim.resource_id}/{claim.attempt}/video.mp4"
