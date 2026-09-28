from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Protocol
from uuid import uuid4

from app.integrations.media_runner_models import MediaRunnerClientError, RunnerArtifact
from app.services.downloads.errors import (
    MediaInspectionAuthRequired,
    MediaInspectionConfigurationMissing,
    MediaInspectionContentRestricted,
    MediaInspectionDrmProtected,
    MediaInspectionFailure,
    MediaInspectionFormatUnavailable,
    MediaInspectionGeoRestricted,
    MediaInspectionGuestContextRequired,
    MediaInspectionLinkUnavailable,
    MediaInspectionMediaUnsupported,
    MediaInspectionRateLimited,
    MediaInspectionSessionExpired,
    MediaInspectionSessionNotReady,
    MediaInspectionTemporarilyUnavailable,
    MediaInspectionTimeout,
    MediaInspectionUnsupported,
    MediaInspectionVerificationFailed,
)
from app.services.downloads.inspection_models import RunnerInspection
from app.services.downloads.rules.enums import MediaKind
from app.services.downloads.rules.formats import DownloadPlan
from app.services.provider_route_admission import (
    RouteAdmissionUnavailable,
    RouteCoolingDown,
    RouteProbeTimeout,
)
from app.services.provider_types import (
    ProviderAccessContextRef,
    ProviderAccessMode,
    ProviderCanaryOutcome,
    ProviderCanaryResult,
    ProviderCanaryStage,
)
from app.workers.canary.targets import ProviderCanaryTarget
from app.workers.runner.provider_registry import provider_profile

_INSPECTION_ERRORS: tuple[tuple[type[Exception], str], ...] = (
    (MediaInspectionConfigurationMissing, "provider_configuration_missing"),
    (MediaInspectionGuestContextRequired, "guest_context_required"),
    (MediaInspectionAuthRequired, "provider_auth_required"),
    (MediaInspectionSessionExpired, "provider_session_expired"),
    (MediaInspectionSessionNotReady, "provider_session_not_ready"),
    (MediaInspectionVerificationFailed, "provider_verification_failed"),
    (MediaInspectionRateLimited, "provider_rate_limited"),
    (MediaInspectionGeoRestricted, "provider_geo_restricted"),
    (MediaInspectionContentRestricted, "provider_content_restricted"),
    (MediaInspectionDrmProtected, "provider_drm_protected"),
    (MediaInspectionTemporarilyUnavailable, "provider_temporarily_unavailable"),
    (MediaInspectionLinkUnavailable, "provider_link_unavailable"),
    (MediaInspectionMediaUnsupported, "provider_media_unsupported"),
    (MediaInspectionFormatUnavailable, "format_unavailable"),
    (MediaInspectionUnsupported, "provider_unsupported"),
    (MediaInspectionTimeout, "inspection_timeout"),
    (MediaInspectionFailure, "inspection_failed"),
)
_RUNNER_ERRORS = {
    "canary_internal_error",
    "download_failed",
    "download_timeout",
    "client_context_mismatch",
    "extractor_regression",
    "format_unavailable",
    "invalid_artifact",
    "media_probe_failed",
    "inspection_timeout",
    "provider_configuration_missing",
    "provider_auth_required",
    "provider_session_expired",
    "provider_session_not_ready",
    "provider_verification_failed",
    "provider_rate_limited",
    "provider_link_unavailable",
    "provider_temporarily_unavailable",
    "runner_dependency_unavailable",
    "engine_unavailable",
    "runner_unavailable",
    "workspace_limit_exceeded",
    "egress_challenged",
    "pot_required",
    "pot_rejected",
    "pot_provider_unavailable",
    "pot_provider_release_mismatch",
    "runner_release_mismatch",
    "runner_release_changed",
    "drm_protected",
    "content_private",
    "content_not_entitled",
    "content_preview_only",
    "content_supporter_only",
    "content_paid_only",
    "content_export_required",
    "content_access_metadata_invalid",
    "content_entitlement_unknown",
    "credential_required",
    "guest_context_required",
    "provider_session_not_allowed",
    "credential_expired",
    "credential_rejected",
    "credential_revoked",
    "credential_entitlement_drift",
    "provider_session_unavailable",
    "provider_geo_restricted",
    "provider_media_unsupported",
    "provider_unsupported",
    "invalid_artifact_path",
}
_FORMAT_DRIFT_ATTEMPTS = 3


class CanaryRepository(Protocol):
    async def save(self, result: ProviderCanaryResult) -> None: ...

    async def latest_checked_at(
        self,
        target_id: str,
        profile_version: str,
        stage: ProviderCanaryStage,
        access_mode: ProviderAccessMode,
        engine_commit: str,
        egress_affinity_id: str,
        client_profile_id: str,
        context_generation_id: str,
    ) -> datetime | None: ...


class CanaryRunner(Protocol):
    async def context(
        self,
        url: str,
        *,
        access_mode: ProviderAccessMode,
    ) -> ProviderAccessContextRef: ...

    async def inspect(
        self,
        url: str,
        *,
        access_mode: ProviderAccessMode,
    ) -> RunnerInspection: ...

    async def download(
        self,
        task_id: str,
        url: str,
        plan: DownloadPlan | None,
        *,
        expected_provider_media_id: str,
        expected_extractor_key: str,
        access_context: ProviderAccessContextRef,
        media_kind: MediaKind = MediaKind.VIDEO,
    ) -> RunnerArtifact: ...


class WorkspaceCleaner(Protocol):
    async def cleanup(self, task_id: str, workspace: Path | None) -> None: ...


class ProviderCanaryService:
    def __init__(
        self,
        repository: CanaryRepository,
        runner: CanaryRunner,
        cleaner: WorkspaceCleaner,
        *,
        now: Callable[[], datetime],
        timer: Callable[[], float] = monotonic,
    ) -> None:
        self._repository = repository
        self._runner = runner
        self._cleaner = cleaner
        self._now = now
        self._timer = timer

    async def context_for(
        self,
        target: ProviderCanaryTarget,
    ) -> ProviderAccessContextRef:
        profile = provider_profile(target.safe_url())
        context = await self._runner.context(
            target.safe_url(),
            access_mode=target.access_mode,
        )
        if (
            context.provider_key != target.provider_key
            or context.profile_version != profile.version
            or context.access_mode is not target.access_mode
        ):
            raise MediaRunnerClientError("client_context_mismatch", 502)
        return context

    async def execute(
        self,
        target: ProviderCanaryTarget,
        *,
        expected_context: ProviderAccessContextRef | None = None,
        context_error: Exception | None = None,
    ) -> ProviderCanaryResult:
        started = self._timer()
        task_id = f"canary_{uuid4().hex}"
        workspace = None
        profile = provider_profile(target.safe_url())
        context = expected_context
        error: str | None = None
        try:
            if context_error is not None:
                raise context_error
            if context is None:
                context = await self.context_for(target)
            inspection = await self._runner.inspect(
                target.safe_url(),
                access_mode=target.access_mode,
            )
            inspected_context = inspection.access_context
            if inspected_context != context:
                raise MediaRunnerClientError("client_context_mismatch", 502)
            context = inspected_context
            if target.stage is ProviderCanaryStage.MEDIA:
                artifact, inspection = await self._download_media(
                    target,
                    task_id,
                    inspection,
                )
                context = inspection.access_context
                workspace = artifact.workspace
        except Exception as exc:
            error = _stable_error(exc)
        finally:
            if target.stage is ProviderCanaryStage.MEDIA:
                await self._cleaner.cleanup(task_id, workspace)
        result = ProviderCanaryResult(
            target_id=target.target_id,
            provider_key=target.provider_key,
            profile_version=context.profile_version if context else profile.version,
            stage=target.stage,
            access_mode=target.access_mode,
            outcome=(
                ProviderCanaryOutcome.SUCCEEDED
                if error is None
                else ProviderCanaryOutcome.FAILED
            ),
            stable_error_code=error,
            checked_at=self._now(),
            duration_ms=max(0, round((self._timer() - started) * 1000)),
            engine_commit=context.engine_commit if context else "unresolved",
            egress_affinity_id=(
                context.egress_affinity_id if context else "unresolved"
            ),
            client_profile_id=(context.client_profile_id if context else "unresolved"),
            context_generation_id=(context.generation_id if context else "unresolved"),
        )
        await self._repository.save(result)
        return result

    async def _download_media(
        self,
        target: ProviderCanaryTarget,
        task_id: str,
        inspection: RunnerInspection,
    ) -> tuple[RunnerArtifact, RunnerInspection]:
        """Retry only a rendition rotation, never a platform/access failure."""
        expected_context = inspection.access_context
        for attempt in range(_FORMAT_DRIFT_ATTEMPTS):
            if not inspection.formats:
                raise MediaRunnerClientError("format_unavailable", 409)
            # The browser selects the first advertised format by default. Keep
            # the media canary on the same path so it detects regressions in
            # the format most users actually download.
            canary_format = inspection.formats[0]
            if canary_format.plan is None:
                raise MediaRunnerClientError("format_unavailable", 409)
            try:
                artifact = await self._runner.download(
                    task_id,
                    target.safe_url(),
                    canary_format.plan,
                    expected_provider_media_id=inspection.provider_media_id,
                    expected_extractor_key=inspection.extractor_key,
                    access_context=inspection.access_context,
                )
                return artifact, inspection
            except MediaRunnerClientError as exc:
                if (
                    exc.code != "format_unavailable"
                    or attempt == _FORMAT_DRIFT_ATTEMPTS - 1
                ):
                    raise
                inspection = await self._runner.inspect(
                    target.safe_url(),
                    access_mode=target.access_mode,
                )
                context = inspection.access_context
                if context != expected_context:
                    raise MediaRunnerClientError(
                        "client_context_mismatch", 502
                    ) from exc
        raise AssertionError("unreachable")


def _stable_error(exc: Exception) -> str:
    if isinstance(
        exc,
        (
            MediaRunnerClientError,
            RouteCoolingDown,
            RouteProbeTimeout,
            RouteAdmissionUnavailable,
        ),
    ):
        if exc.code in _RUNNER_ERRORS:
            return exc.code
        return "canary_internal_error"
    return next(
        (
            code
            for error_type, code in _INSPECTION_ERRORS
            if isinstance(exc, error_type)
        ),
        "canary_internal_error",
    )
