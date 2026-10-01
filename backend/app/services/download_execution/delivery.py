from __future__ import annotations

import asyncio
from uuid import UUID

from app.services.download_execution.artifact import (
    VerifiedArtifact,
    artifact_object_key,
)
from app.services.download_execution.errors import (
    ExecutionOwnershipLost,
    ExecutionPersistenceUnavailable,
    LeaseInfrastructureError,
    LeaseLost,
)
from app.services.download_execution.models import (
    ArtifactDetails,
    DownloadExecutionSettings,
    ExecutionDisposition,
)
from app.services.download_execution.monitor import LeaseMonitor
from app.services.download_execution.ports import Clock, ExecutionStorage
from app.services.download_execution.transitions import ExecutionTransitions
from app.services.downloads.rules.enums import DownloadErrorCode, DownloadStage
from app.services.provider_types import ExecutionContext


class ArtifactDelivery:
    def __init__(
        self,
        storage: ExecutionStorage,
        settings: DownloadExecutionSettings,
        clock: Clock,
        transitions: ExecutionTransitions,
    ) -> None:
        self._storage = storage
        self._settings = settings
        self._clock = clock
        self._transitions = transitions

    async def run(
        self,
        monitor: LeaseMonitor,
        job_id: UUID,
        attempt: int,
        artifact: VerifiedArtifact,
        execution_context: ExecutionContext,
    ) -> ExecutionDisposition:
        key = artifact_object_key(job_id, attempt, artifact.container)
        try:
            uploaded = await monitor.run_fixed(
                lambda: self._storage.upload(key, artifact.path, artifact.content_type),
                stage=DownloadStage.UPLOADING,
                progress=99,
                drain_on_abort=True,
            )
        except (LeaseLost, ExecutionOwnershipLost):
            await self._transitions.delete(key)
            return await self._transitions.convergence(job_id)
        except (LeaseInfrastructureError, ExecutionPersistenceUnavailable):
            await self._transitions.delete(key)
            return ExecutionDisposition.REQUEUE
        except asyncio.CancelledError:
            await self._transitions.delete(key)
            raise
        except Exception:
            await self._transitions.delete(key)
            return await self._transitions.fail(
                job_id, attempt, DownloadErrorCode.STORAGE_UNAVAILABLE
            )
        if uploaded != artifact.size_bytes:
            await self._transitions.delete(key)
            return await self._transitions.fail(
                job_id, attempt, DownloadErrorCode.MEDIA_VALIDATION_FAILED
            )
        details = ArtifactDetails(
            bucket=self._settings.bucket,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            duration_ms=artifact.duration_ms,
            container=artifact.container,
            content_type=artifact.content_type,
            media_metadata={
                "video_streams": artifact.video_streams,
                "audio_streams": artifact.audio_streams,
                "media_kind": artifact.media_kind.value,
                "asset_count": artifact.asset_count,
                "execution_context": execution_context.to_document(),
            },
        )
        return await self._transitions.complete(job_id, attempt, key, details)
