from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from uuid import UUID

from app.services.import_execution.document_ports import (
    DocumentImportExecutionRepository,
)
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
    DocumentImportVerifier,
    ImportExecutionStorage,
    ImportWorkspaceManager,
)
from app.services.imports.models import ImportDisposition
from app.services.imports.rules.enums import ContentKind, ImportErrorCode


class DocumentImportExecution:
    def __init__(
        self,
        *,
        repository: DocumentImportExecutionRepository,
        storage: ImportExecutionStorage,
        workspace: ImportWorkspaceManager,
        verifier: DocumentImportVerifier,
        clock: Clock,
        settings: ImportExecutionSettings,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._workspace = workspace
        self._verifier = verifier
        self._clock = clock
        self._settings = settings

    async def execute(
        self,
        resource_id: UUID,
        content_kind: ContentKind,
        attempt: int,
        expected_version: int,
    ) -> ImportDisposition:
        if content_kind is not ContentKind.SCREENPLAY:
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
                    lambda: self._verifier(workspace.input_path, claim),
                    lambda: self._heartbeat(claim, stage="verifying", progress=75),
                    interval=self._settings.heartbeat_interval,
                )
                original_key, normalized_key = _artifact_keys(claim)
                await monitored(
                    lambda: self._storage.promote(
                        claim.object_key,
                        original_key,
                        expected_size_bytes=artifact.original_size_bytes,
                        sha256=artifact.original_sha256,
                        content_type=artifact.original_content_type,
                    ),
                    lambda: self._heartbeat(claim, stage="uploading", progress=90),
                    interval=self._settings.heartbeat_interval,
                )
                await monitored(
                    lambda: self._storage.upload_verified(
                        artifact.normalized_path,
                        normalized_key,
                        expected_size_bytes=artifact.normalized_size_bytes,
                        sha256=artifact.normalized_sha256,
                        content_type="text/markdown; charset=utf-8",
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
                return await self._reject(claim, exc.code)
            except Exception:
                return ImportDisposition.RETRY
            with suppress(Exception):
                await self._storage.delete(claim.object_key)
            return ImportDisposition.ACK
        finally:
            with suppress(Exception):
                await self._workspace.cleanup(task_id, workspace_path)

    async def _reject(
        self, claim: ImportVerificationClaim, error_code: ImportErrorCode
    ) -> ImportDisposition:
        try:
            await self._repository.fail_verification(
                claim,
                error_code,
                worker_id=self._settings.worker_id,
                now=self._clock(),
            )
        except Exception:
            return ImportDisposition.RETRY
        with suppress(Exception):
            await self._storage.delete(claim.object_key)
        return ImportDisposition.ACK

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


def _artifact_keys(claim: ImportVerificationClaim) -> tuple[str, str]:
    if claim.content_kind is not ContentKind.SCREENPLAY or claim.attempt < 1:
        raise ImportVerificationRejected(
            ImportErrorCode.DOCUMENT_STRUCTURE_INVALID,
            "unsupported document artifact identity",
        )
    prefix = f"documents/{claim.resource_id}/{claim.attempt}"
    return f"{prefix}/original", f"{prefix}/document.md"
