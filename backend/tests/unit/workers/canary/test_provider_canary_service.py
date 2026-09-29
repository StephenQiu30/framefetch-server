from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.integrations.media_runner_models import MediaRunnerClientError, RunnerArtifact
from app.services.downloads.errors import (
    MediaInspectionAuthRequired,
    MediaInspectionConfigurationMissing,
    MediaInspectionFormatUnavailable,
    MediaInspectionSessionExpired,
)
from app.services.downloads.inspection_models import RunnerFormat, RunnerInspection
from app.services.downloads.rules.formats import DownloadPlan
from app.services.provider_types import (
    ProviderAccessContextRef,
    ProviderAccessMode,
    ProviderCanaryOutcome,
    ProviderCanaryResult,
    ProviderCanaryStage,
)
from app.workers.canary.service import ProviderCanaryService, _stable_error
from app.workers.canary.targets import ProviderCanaryTarget
from tests.unit.workers.runner.helpers import download_request

NOW = datetime(2026, 8, 11, 5, tzinfo=UTC)
URL = "https://www.youtube.com/watch?v=owned"


def test_download_failure_keeps_a_stable_runner_error() -> None:
    assert _stable_error(MediaRunnerClientError("download_failed", 502)) == (
        "download_failed"
    )


@pytest.mark.parametrize(
    "code",
    (
        "engine_unavailable",
        "pot_provider_release_mismatch",
        "runner_release_mismatch",
        "runner_release_changed",
    ),
)
def test_release_identity_failure_keeps_a_stable_canary_error(code: str) -> None:
    assert _stable_error(MediaRunnerClientError(code, 503)) == code


class Repository:
    def __init__(self) -> None:
        self.results: list[ProviderCanaryResult] = []

    async def save(self, result: ProviderCanaryResult) -> None:
        self.results.append(result)

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
    ) -> datetime | None:
        return None


class Cleaner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path | None]] = []

    async def cleanup(self, task_id: str, workspace: Path | None) -> None:
        self.calls.append((task_id, workspace))


class Runner:
    def __init__(
        self,
        workspace: Path,
        *,
        fail: bool = False,
        format_drifts: int = 0,
    ) -> None:
        self.workspace = workspace
        self.fail = fail
        self.format_drifts = format_drifts
        self.downloaded = False
        self.context_calls = 0
        self.inspections = 0
        self.download_calls = 0
        self.download_plans: list[DownloadPlan] = []

    async def context(
        self,
        url: str,
        *,
        access_mode: ProviderAccessMode,
    ) -> ProviderAccessContextRef:
        assert url == URL
        self.context_calls += 1
        return _context(access_mode)

    async def inspect(
        self,
        url: str,
        *,
        access_mode: ProviderAccessMode,
    ) -> RunnerInspection:
        assert url == URL
        self.inspections += 1
        if self.fail:
            raise MediaInspectionAuthRequired(access_mode=access_mode)
        default_request = download_request()
        fallback_request = download_request(height=240, width=320)
        return RunnerInspection(
            extractor_key="Youtube",
            provider_media_id="owned",
            title="Authorized canary",
            duration_seconds=30,
            formats=(
                RunnerFormat("1080p", default_request.plan.to_domain()),
                RunnerFormat("240p", fallback_request.plan.to_domain()),
            ),
            access_context=_context(access_mode),
        )

    async def download(self, *args: object, **kwargs: object) -> RunnerArtifact:
        self.download_calls += 1
        assert isinstance(args[2], DownloadPlan)
        self.download_plans.append(args[2])
        if self.download_calls <= self.format_drifts:
            raise MediaRunnerClientError("format_unavailable", 409)
        self.downloaded = True
        return RunnerArtifact(
            task_id=str(args[0]),
            workspace=self.workspace,
            artifact=self.workspace / "video.mp4",
            size_bytes=1024,
            sha256="a" * 64,
            duration_seconds=30,
            container="mp4",
            video_streams=1,
            audio_streams=1,
        )


def target(
    stage: ProviderCanaryStage,
    access_mode: ProviderAccessMode = ProviderAccessMode.ANONYMOUS,
) -> ProviderCanaryTarget:
    return ProviderCanaryTarget(
        target_id=(
            "youtube-operator"
            if access_mode is ProviderAccessMode.OPERATOR_MANAGED
            else "youtube-public"
        ),
        provider_key="youtube",
        stage=stage,
        access_mode=access_mode,
        url=URL,
    )


@pytest.mark.asyncio
async def test_full_canary_downloads_and_cleans_verified_media(tmp_path: Path) -> None:
    repository, cleaner, runner = Repository(), Cleaner(), Runner(tmp_path)
    ticks = iter((1.0, 1.25))
    service = ProviderCanaryService(
        repository, runner, cleaner, now=lambda: NOW, timer=lambda: next(ticks)
    )

    result = await service.execute(target(ProviderCanaryStage.MEDIA))

    assert result.outcome is ProviderCanaryOutcome.SUCCEEDED
    assert result.duration_ms == 250
    assert runner.downloaded is True
    assert runner.download_plans[0].height == 1080
    assert runner.download_plans[0].width == 1920
    assert repository.results == [result]
    assert cleaner.calls[0][1] == tmp_path


@pytest.mark.asyncio
async def test_media_canary_reinspects_bounded_format_drift(tmp_path: Path) -> None:
    repository, cleaner = Repository(), Cleaner()
    runner = Runner(tmp_path, format_drifts=2)
    ticks = iter((1.0, 1.5))
    service = ProviderCanaryService(
        repository, runner, cleaner, now=lambda: NOW, timer=lambda: next(ticks)
    )

    result = await service.execute(target(ProviderCanaryStage.MEDIA))

    assert result.outcome is ProviderCanaryOutcome.SUCCEEDED
    assert runner.inspections == 3
    assert runner.download_calls == 3


@pytest.mark.asyncio
async def test_media_canary_translates_runner_drm_failure(tmp_path: Path) -> None:
    class DrmRunner(Runner):
        async def download(self, *args: object, **kwargs: object) -> RunnerArtifact:
            raise MediaRunnerClientError("drm_protected", 422)

    repository, cleaner = Repository(), Cleaner()
    ticks = iter((1.0, 1.1))
    service = ProviderCanaryService(
        repository,
        DrmRunner(tmp_path),
        cleaner,
        now=lambda: NOW,
        timer=lambda: next(ticks),
    )

    result = await service.execute(target(ProviderCanaryStage.MEDIA))

    assert result.outcome is ProviderCanaryOutcome.FAILED
    assert result.stable_error_code == "drm_protected"


@pytest.mark.asyncio
async def test_media_canary_translates_runner_challenge_failure(tmp_path: Path) -> None:
    class ChallengeRunner(Runner):
        async def download(self, *args: object, **kwargs: object) -> RunnerArtifact:
            raise MediaRunnerClientError("egress_challenged", 422)

    repository, cleaner = Repository(), Cleaner()
    ticks = iter((1.0, 1.1))
    service = ProviderCanaryService(
        repository,
        ChallengeRunner(tmp_path),
        cleaner,
        now=lambda: NOW,
        timer=lambda: next(ticks),
    )

    result = await service.execute(target(ProviderCanaryStage.MEDIA))

    assert result.outcome is ProviderCanaryOutcome.FAILED
    assert result.stable_error_code == "egress_challenged"


@pytest.mark.asyncio
async def test_media_canary_preserves_transient_provider_failure(
    tmp_path: Path,
) -> None:
    class ChallengeRunner(Runner):
        async def download(self, *args: object, **kwargs: object) -> RunnerArtifact:
            raise MediaRunnerClientError("provider_temporarily_unavailable", 503)

    repository, cleaner = Repository(), Cleaner()
    ticks = iter((1.0, 1.1))
    service = ProviderCanaryService(
        repository,
        ChallengeRunner(tmp_path),
        cleaner,
        now=lambda: NOW,
        timer=lambda: next(ticks),
    )

    result = await service.execute(target(ProviderCanaryStage.MEDIA))

    assert result.outcome is ProviderCanaryOutcome.FAILED
    assert result.stable_error_code == "provider_temporarily_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "runner_error",
    ("pot_provider_unavailable", "provider_session_unavailable"),
)
async def test_media_canary_preserves_provider_dependency_outages(
    tmp_path: Path,
    runner_error: str,
) -> None:
    class DependencyFailureRunner(Runner):
        async def download(self, *args: object, **kwargs: object) -> RunnerArtifact:
            raise MediaRunnerClientError(runner_error, 503)

    repository, cleaner = Repository(), Cleaner()
    ticks = iter((1.0, 1.1))
    service = ProviderCanaryService(
        repository,
        DependencyFailureRunner(tmp_path),
        cleaner,
        now=lambda: NOW,
        timer=lambda: next(ticks),
    )

    result = await service.execute(target(ProviderCanaryStage.MEDIA))

    assert result.outcome is ProviderCanaryOutcome.FAILED
    assert result.stable_error_code == runner_error


@pytest.mark.asyncio
async def test_metadata_failure_is_persisted_as_stable_access_error(
    tmp_path: Path,
) -> None:
    repository, cleaner = Repository(), Cleaner()
    ticks = iter((1.0, 1.1))
    service = ProviderCanaryService(
        repository,
        Runner(tmp_path, fail=True),
        cleaner,
        now=lambda: NOW,
        timer=lambda: next(ticks),
    )

    result = await service.execute(target(ProviderCanaryStage.METADATA))

    assert result.outcome is ProviderCanaryOutcome.FAILED
    assert result.stable_error_code == "provider_auth_required"
    assert result.access_mode is ProviderAccessMode.ANONYMOUS
    assert result.egress_affinity_id == "default"
    assert cleaner.calls == []


@pytest.mark.asyncio
async def test_metadata_format_failure_keeps_its_stable_error(
    tmp_path: Path,
) -> None:
    class FormatFailureRunner(Runner):
        async def inspect(
            self,
            url: str,
            *,
            access_mode: ProviderAccessMode,
        ) -> RunnerInspection:
            assert url == URL
            raise MediaInspectionFormatUnavailable(access_mode=access_mode)

    repository, cleaner = Repository(), Cleaner()
    ticks = iter((1.0, 1.1))
    service = ProviderCanaryService(
        repository,
        FormatFailureRunner(tmp_path),
        cleaner,
        now=lambda: NOW,
        timer=lambda: next(ticks),
    )

    result = await service.execute(target(ProviderCanaryStage.METADATA))

    assert result.outcome is ProviderCanaryOutcome.FAILED
    assert result.stable_error_code == "format_unavailable"


@pytest.mark.asyncio
async def test_metadata_source_failure_is_reported_as_configuration_missing(
    tmp_path: Path,
) -> None:
    class SourceFailureRunner(Runner):
        async def inspect(
            self,
            url: str,
            *,
            access_mode: ProviderAccessMode,
        ) -> RunnerInspection:
            assert url == URL
            raise MediaInspectionConfigurationMissing(access_mode=access_mode)

    repository, cleaner = Repository(), Cleaner()
    ticks = iter((1.0, 1.1))
    service = ProviderCanaryService(
        repository,
        SourceFailureRunner(tmp_path),
        cleaner,
        now=lambda: NOW,
        timer=lambda: next(ticks),
    )

    result = await service.execute(target(ProviderCanaryStage.METADATA))

    assert result.outcome is ProviderCanaryOutcome.FAILED
    assert result.stable_error_code == "provider_configuration_missing"


@pytest.mark.asyncio
async def test_context_failure_is_not_guessed_as_the_current_runtime(
    tmp_path: Path,
) -> None:
    class ContextFailureRunner(Runner):
        async def context(
            self,
            url: str,
            *,
            access_mode: ProviderAccessMode,
        ) -> ProviderAccessContextRef:
            raise MediaRunnerClientError("runner_unavailable", 503)

    repository, cleaner = Repository(), Cleaner()
    ticks = iter((1.0, 1.1))
    service = ProviderCanaryService(
        repository,
        ContextFailureRunner(tmp_path),
        cleaner,
        now=lambda: NOW,
        timer=lambda: next(ticks),
    )

    result = await service.execute(target(ProviderCanaryStage.METADATA))

    assert result.outcome is ProviderCanaryOutcome.FAILED
    assert result.engine_commit == "unresolved"
    assert result.egress_affinity_id == "unresolved"
    assert result.client_profile_id == "unresolved"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_code", "status"),
    (("runner_unavailable", 503), ("inspection_timeout", 504)),
)
async def test_preflight_context_failure_is_not_retried_or_guessed(
    tmp_path: Path,
    error_code: str,
    status: int,
) -> None:
    repository, cleaner, runner = Repository(), Cleaner(), Runner(tmp_path)
    ticks = iter((1.0, 1.1))
    service = ProviderCanaryService(
        repository,
        runner,
        cleaner,
        now=lambda: NOW,
        timer=lambda: next(ticks),
    )

    result = await service.execute(
        target(ProviderCanaryStage.METADATA),
        context_error=MediaRunnerClientError(error_code, status),
    )

    assert runner.context_calls == 0
    assert runner.inspections == 0
    assert result.stable_error_code == error_code
    assert result.engine_commit == "unresolved"


@pytest.mark.asyncio
async def test_metadata_failure_preserves_operator_attempt_attribution(
    tmp_path: Path,
) -> None:
    class OperatorFailureRunner(Runner):
        async def inspect(
            self,
            url: str,
            *,
            access_mode: ProviderAccessMode,
        ) -> RunnerInspection:
            assert url == URL
            assert access_mode is ProviderAccessMode.OPERATOR_MANAGED
            raise MediaInspectionSessionExpired(
                access_mode=ProviderAccessMode.OPERATOR_MANAGED
            )

    repository, cleaner = Repository(), Cleaner()
    ticks = iter((1.0, 1.1))
    service = ProviderCanaryService(
        repository,
        OperatorFailureRunner(tmp_path),
        cleaner,
        now=lambda: NOW,
        timer=lambda: next(ticks),
    )

    result = await service.execute(
        target(
            ProviderCanaryStage.METADATA,
            ProviderAccessMode.OPERATOR_MANAGED,
        )
    )

    assert result.outcome is ProviderCanaryOutcome.FAILED
    assert result.stable_error_code == "provider_session_expired"
    assert result.access_mode is ProviderAccessMode.OPERATOR_MANAGED


@pytest.mark.asyncio
async def test_anonymous_failure_and_operator_success_are_both_persisted(
    tmp_path: Path,
) -> None:
    class RouteRunner(Runner):
        async def inspect(
            self,
            url: str,
            *,
            access_mode: ProviderAccessMode,
        ) -> RunnerInspection:
            if access_mode is ProviderAccessMode.ANONYMOUS:
                raise MediaInspectionAuthRequired()
            return await super().inspect(url, access_mode=access_mode)

    repository, cleaner = Repository(), Cleaner()
    ticks = iter((1.0, 1.1, 2.0, 2.1))
    service = ProviderCanaryService(
        repository,
        RouteRunner(tmp_path),
        cleaner,
        now=lambda: NOW,
        timer=lambda: next(ticks),
    )

    public_result = await service.execute(target(ProviderCanaryStage.METADATA))
    operator_result = await service.execute(
        target(
            ProviderCanaryStage.METADATA,
            ProviderAccessMode.OPERATOR_MANAGED,
        )
    )

    assert repository.results == [public_result, operator_result]
    assert public_result.outcome is ProviderCanaryOutcome.FAILED
    assert public_result.access_mode is ProviderAccessMode.ANONYMOUS
    assert operator_result.outcome is ProviderCanaryOutcome.SUCCEEDED
    assert operator_result.access_mode is ProviderAccessMode.OPERATOR_MANAGED


@pytest.mark.asyncio
async def test_failure_is_persisted_for_the_explicit_public_route(
    tmp_path: Path,
) -> None:
    class UnattributedFailureRunner(Runner):
        async def inspect(
            self,
            url: str,
            *,
            access_mode: ProviderAccessMode,
        ) -> RunnerInspection:
            assert url == URL
            assert access_mode is ProviderAccessMode.ANONYMOUS
            raise MediaInspectionAuthRequired()

    repository, cleaner = Repository(), Cleaner()
    ticks = iter((1.0, 1.1))
    service = ProviderCanaryService(
        repository,
        UnattributedFailureRunner(tmp_path),
        cleaner,
        now=lambda: NOW,
        timer=lambda: next(ticks),
    )

    result = await service.execute(target(ProviderCanaryStage.METADATA))

    assert result.outcome is ProviderCanaryOutcome.FAILED
    assert result.access_mode is ProviderAccessMode.ANONYMOUS


@pytest.mark.asyncio
async def test_runner_cannot_return_a_different_route_as_public_success(
    tmp_path: Path,
) -> None:
    class MismatchedRunner(Runner):
        async def inspect(
            self,
            url: str,
            *,
            access_mode: ProviderAccessMode,
        ) -> RunnerInspection:
            assert access_mode is ProviderAccessMode.ANONYMOUS
            return await super().inspect(
                url,
                access_mode=ProviderAccessMode.OPERATOR_MANAGED,
            )

    repository, cleaner = Repository(), Cleaner()
    ticks = iter((1.0, 1.1))
    service = ProviderCanaryService(
        repository,
        MismatchedRunner(tmp_path),
        cleaner,
        now=lambda: NOW,
        timer=lambda: next(ticks),
    )

    result = await service.execute(target(ProviderCanaryStage.METADATA))

    assert result.outcome is ProviderCanaryOutcome.FAILED
    assert result.stable_error_code == "client_context_mismatch"
    assert result.access_mode is ProviderAccessMode.ANONYMOUS
    assert result.profile_version == "youtube"


def _context(access_mode: ProviderAccessMode) -> ProviderAccessContextRef:
    operator = access_mode is ProviderAccessMode.OPERATOR_MANAGED
    return ProviderAccessContextRef(
        provider_key="youtube",
        profile_version="youtube",
        access_mode=access_mode,
        credential_version_id="browser" if operator else None,
        egress_affinity_id="default",
        client_profile_id="yt-dlp-default",
        attestation_provider_version=None,
        engine_commit="5d6b8c8cd19785c3086ae3a9ec618c45e25eb3bc",
        runtime_revision="a" * 64,
    )
