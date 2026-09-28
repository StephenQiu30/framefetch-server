from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from app.services.download_execution.artifact import verify_artifact
from app.services.download_execution.delivery import ArtifactDelivery
from app.services.download_execution.errors import (
    ArtifactValidationError,
    ExecutionOwnershipLost,
    ExecutionPersistenceUnavailable,
    ExecutionSourceUnavailable,
    LeaseInfrastructureError,
    LeaseLost,
    LegacyContextChanged,
    classify_runner_failure,
)
from app.services.download_execution.models import (
    DownloadExecutionSettings,
    ExecutionDisposition,
)
from app.services.download_execution.monitor import LeaseMonitor
from app.services.download_execution.ports import (
    Clock,
    ExecutionRepository,
    ExecutionRunner,
    ExecutionStorage,
    ThumbnailRecovery,
    UrlDecryptor,
    WorkspaceCleaner,
)
from app.services.download_execution.transitions import ExecutionTransitions
from app.services.downloads.inspection_models import EncryptedUrl
from app.services.downloads.plans import plan_from_documents
from app.services.downloads.rules.enums import (
    AudioCodecFamily,
    DownloadErrorCode,
    DownloadStage,
    MediaKind,
)
from app.services.provider_route_admission import RouteCoolingDown
from app.services.provider_types import ProviderAccessContextRef, ProviderAccessMode


class DownloadExecution:
    def __init__(
        self,
        *,
        repository: ExecutionRepository,
        runner: ExecutionRunner,
        storage: ExecutionStorage,
        url_cipher: UrlDecryptor,
        workspace_cleaner: WorkspaceCleaner,
        clock: Clock,
        settings: DownloadExecutionSettings,
        thumbnail_recovery: ThumbnailRecovery | None = None,
    ) -> None:
        self._repository = repository
        self._runner = runner
        self._storage = storage
        self._url_cipher = url_cipher
        self._cleaner = workspace_cleaner
        self._clock = clock
        self._settings = settings
        self._thumbnail_recovery = thumbnail_recovery
        self._transitions = ExecutionTransitions(repository, storage, settings, clock)
        self._delivery = ArtifactDelivery(storage, settings, clock, self._transitions)

    async def execute(self, job_id: UUID) -> ExecutionDisposition:
        try:
            claimed = await self._repository.claim_job(
                job_id,
                self._settings.worker_id,
                self._clock(),
                self._settings.lease_for,
            )
        except ExecutionSourceUnavailable:
            return ExecutionDisposition.ACK
        except Exception:
            return ExecutionDisposition.REQUEUE
        if claimed is None:
            return await self._transitions.duplicate(job_id)
        return await self._execute_claimed(job_id, claimed.attempt)

    async def _execute_claimed(
        self, job_id: UUID, attempt: int
    ) -> ExecutionDisposition:
        task_id = f"download_{job_id.hex}_{attempt}"
        workspace: Path | None = None
        monitor = self._monitor(job_id, attempt, task_id)
        try:
            try:
                source = await self._repository.get_job_source(
                    job_id,
                    self._settings.worker_id,
                    attempt,
                    self._clock(),
                )
            except ExecutionSourceUnavailable:
                return await self._transitions.fail(
                    job_id, attempt, DownloadErrorCode.UNSUPPORTED_SOURCE
                )
            except ExecutionOwnershipLost:
                return await self._transitions.convergence(job_id)
            except Exception:
                return ExecutionDisposition.REQUEUE
            try:
                url = self._url_cipher.decrypt(
                    EncryptedUrl(
                        source.url_ciphertext,
                        source.url_nonce,
                        source.url_key_id,
                    )
                )
                media_kind = _media_kind(source.semantic_plan)
                plan = (
                    None
                    if media_kind
                    in {MediaKind.IMAGE_GALLERY, MediaKind.VIDEO_COLLECTION}
                    else plan_from_documents(
                        source.semantic_plan, source.provider_hints
                    )
                )
                access_context = ProviderAccessContextRef.from_document(
                    source.access_context
                )
            except Exception:
                return await self._transitions.fail(
                    job_id, attempt, DownloadErrorCode.INTERNAL_ERROR
                )
            try:
                # The Runner re-inspects media identity and the selected format
                # before writing. Refresh only a code-generation change here;
                # never silently switch account, egress, engine or policy.
                current_context = await monitor.run_fixed(
                    lambda: self._runner.context(url, access_context.access_mode),
                    stage=DownloadStage.REVALIDATING,
                    progress=0,
                    drain_on_abort=False,
                )
                candidate = replace(
                    access_context,
                    runtime_revision=current_context.runtime_revision,
                    credential_version_id=(
                        current_context.credential_version_id
                        if access_context.access_mode is ProviderAccessMode.GUEST
                        else access_context.credential_version_id
                    ),
                )
                if candidate == current_context:
                    access_context = current_context
                elif access_context.runtime_revision == "legacy":
                    raise LegacyContextChanged("legacy context route changed")
                await monitor.run_fixed(
                    lambda: self._repository.record_execution_context(
                        job_id,
                        self._settings.worker_id,
                        attempt,
                        access_context,
                        self._clock(),
                    ),
                    stage=DownloadStage.REVALIDATING,
                    progress=0,
                    drain_on_abort=False,
                )
                artifact = await monitor.run_download(
                    url,
                    plan,
                    provider_media_id=source.provider_media_id,
                    extractor_key=source.extractor_key,
                    access_context=access_context,
                    media_kind=media_kind,
                    asset_count=_asset_count(source.semantic_plan),
                )
                workspace = artifact.workspace
            except (LeaseLost, ExecutionOwnershipLost):
                return await self._transitions.convergence(job_id)
            except (LeaseInfrastructureError, ExecutionPersistenceUnavailable):
                return ExecutionDisposition.REQUEUE
            except asyncio.CancelledError:
                raise
            except RouteCoolingDown as exc:
                return await self._transitions.fail(
                    job_id,
                    attempt,
                    DownloadErrorCode.PROVIDER_RATE_LIMITED,
                    retry_not_before=exc.retry_at,
                )
            except Exception as exc:
                return await self._transitions.fail(
                    job_id,
                    attempt,
                    classify_runner_failure(exc),
                    error_message=str(exc),
                )
            try:
                verified = await monitor.run_fixed(
                    lambda: verify_artifact(
                        artifact,
                        task_id=task_id,
                        shared_root=self._settings.workspace_root,
                        max_size_bytes=self._settings.max_file_size_bytes,
                        expected_audio=(
                            plan is None
                            or plan.audio_codec_family is not AudioCodecFamily.NONE
                        ),
                    ),
                    stage=DownloadStage.VERIFYING,
                    progress=90,
                    drain_on_abort=True,
                )
            except ArtifactValidationError as exc:
                return await self._transitions.fail(
                    job_id,
                    attempt,
                    DownloadErrorCode.MEDIA_VALIDATION_FAILED,
                    error_message=str(exc),
                )
            except (LeaseLost, ExecutionOwnershipLost):
                return await self._transitions.convergence(job_id)
            except (LeaseInfrastructureError, ExecutionPersistenceUnavailable):
                return ExecutionDisposition.REQUEUE
            thumbnail_recovery = self._thumbnail_recovery
            if thumbnail_recovery is not None and not source.thumbnail_available:
                try:
                    await monitor.run_fixed(
                        lambda: thumbnail_recovery.recover(
                            source.inspection_id,
                            source.owner_hash,
                            verified.path,
                        ),
                        stage=DownloadStage.VERIFYING,
                        progress=94,
                        drain_on_abort=True,
                    )
                except (LeaseLost, ExecutionOwnershipLost):
                    return await self._transitions.convergence(job_id)
                except (LeaseInfrastructureError, ExecutionPersistenceUnavailable):
                    return ExecutionDisposition.REQUEUE
                except Exception:
                    # Thumbnail recovery is best-effort and must never turn a
                    # verified media download into a failed job.
                    pass
            return await self._delivery.run(
                monitor, job_id, attempt, verified, access_context
            )
        finally:
            with suppress(Exception):
                await self._cleaner.cleanup(task_id, workspace)

    def _monitor(self, job_id: UUID, attempt: int, task_id: str) -> LeaseMonitor:
        return LeaseMonitor(
            repository=self._repository,
            runner=self._runner,
            job_id=job_id,
            worker_id=self._settings.worker_id,
            attempt=attempt,
            task_id=task_id,
            clock=self._clock,
            lease_for=self._settings.lease_for,
            interval=self._settings.heartbeat_interval,
        )


def _media_kind(document: dict[str, object]) -> MediaKind:
    value = document.get("media_kind", MediaKind.VIDEO.value)
    if not isinstance(value, str):
        raise ValueError("unknown media kind")
    try:
        return MediaKind(value)
    except ValueError as exc:
        raise ValueError("unknown media kind") from exc


def _asset_count(document: dict[str, object]) -> int:
    value = document.get("asset_count", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid asset count")
    return value
