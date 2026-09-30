from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace

import pytest
from app.integrations.media_runner_models import MediaRunnerClientError, RunnerArtifact
from app.services.download_execution.models import ExecutionDisposition
from app.services.downloads.plans import plan_to_documents
from app.services.downloads.rules.enums import AudioCodecFamily, DownloadErrorCode
from app.services.downloads.rules.formats import ProviderHints
from app.services.provider_types import ProviderAccessContextRef
from tests.unit.services.download_execution.helpers import download_plan, fixture


def artifact(tmp_path, data: bytes = b"controlled-video") -> RunnerArtifact:
    workspace = tmp_path / "task-workspace"
    workspace.mkdir(parents=True)
    path = workspace / "artifact.mp4"
    path.write_bytes(data)
    return RunnerArtifact(
        task_id="placeholder",
        workspace=workspace,
        artifact=path,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        duration_seconds=30.0,
        container="mp4",
        video_streams=1,
        audio_streams=1,
    )


@pytest.mark.asyncio
async def test_success_revalidates_identity_uploads_and_completes(tmp_path) -> None:
    case = fixture(artifact(tmp_path))
    case.runner.delay = 0.004

    result = await case.execution.execute(case.job_id)

    assert result is ExecutionDisposition.ACK
    download_kwargs = case.runner.download_arguments[3]
    assert download_kwargs["expected_provider_media_id"] == "video-1"
    assert download_kwargs["expected_extractor_key"] == "Controlled"
    assert download_kwargs["access_context"].provider_key == "generic"
    assert case.storage.uploads[0][0] == (f"downloads/{case.job_id}/1/video.mp4")
    assert case.repository.success.sha256 == case.runner.artifact.sha256
    assert case.repository.success.media_metadata["execution_access_context"] == (
        download_kwargs["access_context"].to_document()
    )
    stages = [item[0] for item in case.repository.heartbeats]
    assert "downloading" in stages
    assert stages[-2:] == ["verifying", "uploading"]
    assert [item[1] for item in case.repository.heartbeats] == sorted(
        item[1] for item in case.repository.heartbeats
    )
    assert case.cleaner.calls[0][1] == case.runner.artifact.workspace


@pytest.mark.asyncio
async def test_queued_legacy_job_uses_current_code_generation(tmp_path) -> None:
    case = fixture(artifact(tmp_path))
    old_document = dict(case.repository.source.access_context)
    old_document.pop("runtime_revision")
    case.repository.source.access_context = old_document
    case.runner.current_context = ProviderAccessContextRef.from_document(
        {**old_document, "runtime_revision": "b" * 64}
    )

    assert await case.execution.execute(case.job_id) is ExecutionDisposition.ACK
    assert case.repository.success is not None
    submitted = case.runner.download_arguments[3]["access_context"]
    assert submitted == case.runner.current_context
    assert case.repository.success.media_metadata["execution_access_context"] == (
        submitted.to_document()
    )


@pytest.mark.asyncio
async def test_queued_job_does_not_silently_switch_egress(tmp_path) -> None:
    case = fixture(artifact(tmp_path))
    case.runner.current_context = ProviderAccessContextRef.from_document(
        {
            **case.repository.source.access_context,
            "runtime_revision": "b" * 64,
            "egress_affinity_id": "different-egress",
        }
    )

    assert await case.execution.execute(case.job_id) is ExecutionDisposition.ACK
    submitted = case.runner.download_arguments[3]["access_context"]
    assert submitted.egress_affinity_id == "default"


@pytest.mark.asyncio
async def test_legacy_job_with_changed_route_fails_without_retry(tmp_path) -> None:
    case = fixture(artifact(tmp_path))
    old_document = dict(case.repository.source.access_context)
    old_document.pop("runtime_revision")
    case.repository.source.access_context = old_document
    case.runner.current_context = ProviderAccessContextRef.from_document(
        {
            **old_document,
            "runtime_revision": "b" * 64,
            "egress_affinity_id": "different-egress",
        }
    )

    assert await case.execution.execute(case.job_id) is ExecutionDisposition.ACK
    assert case.runner.download_arguments is None
    assert case.repository.failure["error_code"] == "format_unavailable"
    assert case.repository.failure["error_message"] == "client_context_mismatch"
    assert case.repository.failure["retryable"] is False


@pytest.mark.asyncio
async def test_success_accepts_a_verified_silent_video(tmp_path) -> None:
    case = fixture(replace(artifact(tmp_path), audio_streams=0))
    silent_plan = replace(
        download_plan(),
        audio_codec_family=AudioCodecFamily.NONE,
        audio_language=None,
        hints=ProviderHints(video_id="video-id"),
    )
    semantic, hints = plan_to_documents(silent_plan)
    case.repository.source.semantic_plan = semantic
    case.repository.source.provider_hints = hints

    result = await case.execution.execute(case.job_id)

    assert result is ExecutionDisposition.ACK
    assert case.repository.success is not None
    assert case.repository.success.media_metadata["audio_streams"] == 0


@pytest.mark.asyncio
async def test_success_recovers_thumbnail_before_upload(tmp_path) -> None:
    case = fixture(artifact(tmp_path), recover_thumbnail=True)

    result = await case.execution.execute(case.job_id)

    assert result is ExecutionDisposition.ACK
    assert case.thumbnail_recovery.calls == [
        (
            case.repository.source.inspection_id,
            case.repository.source.owner_hash,
            case.runner.artifact.artifact.resolve(),
        )
    ]
    stages = [item[0] for item in case.repository.heartbeats]
    assert stages[-3:] == ["verifying", "verifying", "uploading"]


@pytest.mark.asyncio
async def test_thumbnail_recovery_failure_does_not_fail_download(tmp_path) -> None:
    case = fixture(artifact(tmp_path), recover_thumbnail=True)
    case.thumbnail_recovery.error = OSError("ffmpeg unavailable")

    result = await case.execution.execute(case.job_id)

    assert result is ExecutionDisposition.ACK
    assert case.repository.success is not None


@pytest.mark.asyncio
async def test_existing_thumbnail_skips_artifact_recovery(tmp_path) -> None:
    case = fixture(artifact(tmp_path), recover_thumbnail=True)
    case.repository.source.thumbnail_available = True

    result = await case.execution.execute(case.job_id)

    assert result is ExecutionDisposition.ACK
    assert case.thumbnail_recovery.calls == []


@pytest.mark.asyncio
async def test_slow_runner_status_does_not_block_download_lease_heartbeat(
    tmp_path,
) -> None:
    case = fixture(artifact(tmp_path), heartbeat_interval=0.01)
    case.runner.delay = 0.03
    case.runner.status_delay = 0.2

    result = await asyncio.wait_for(case.execution.execute(case.job_id), timeout=0.12)

    assert result is ExecutionDisposition.ACK
    assert case.repository.success is not None
    assert case.repository.heartbeats


@pytest.mark.asyncio
async def test_runner_and_storage_failures_converge_before_ack(tmp_path) -> None:
    runner_case = fixture(artifact(tmp_path / "runner"))
    runner_case.runner.error = MediaRunnerClientError("download_timeout", 504)
    assert await runner_case.execution.execute(runner_case.job_id) is (
        ExecutionDisposition.ACK
    )
    assert runner_case.repository.failure["error_code"] == (
        DownloadErrorCode.DOWNLOAD_TIMEOUT.value
    )
    assert runner_case.repository.failure["error_message"] == "download_timeout"
    assert runner_case.repository.failure["retryable"] is True
    assert runner_case.cleaner.calls

    storage_case = fixture(artifact(tmp_path / "storage"))
    storage_case.storage.error = OSError("minio unavailable")
    assert await storage_case.execution.execute(storage_case.job_id) is (
        ExecutionDisposition.ACK
    )
    assert storage_case.repository.failure["error_code"] == (
        DownloadErrorCode.STORAGE_UNAVAILABLE.value
    )
    assert storage_case.repository.failure["retryable"] is True
    assert storage_case.cleaner.calls


@pytest.mark.parametrize(
    ("runner_code", "expected", "retryable"),
    [
        ("credential_required", DownloadErrorCode.PROVIDER_AUTH_REQUIRED, False),
        (
            "provider_session_source_missing",
            DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
            True,
        ),
        (
            "provider_session_permission_denied",
            DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
            True,
        ),
        ("credential_expired", DownloadErrorCode.PROVIDER_SESSION_EXPIRED, False),
        (
            "egress_challenged",
            DownloadErrorCode.PROVIDER_VERIFICATION_FAILED,
            False,
        ),
        ("provider_rate_limited", DownloadErrorCode.PROVIDER_RATE_LIMITED, True),
        (
            "provider_media_unsupported",
            DownloadErrorCode.PROVIDER_MEDIA_UNSUPPORTED,
            False,
        ),
        ("content_private", DownloadErrorCode.PROVIDER_CONTENT_RESTRICTED, False),
        ("drm_protected", DownloadErrorCode.PROVIDER_DRM_PROTECTED, False),
        (
            "provider_new_failure",
            DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
            True,
        ),
        (
            "provider_temporarily_unavailable",
            DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
            True,
        ),
        (
            "download_failed",
            DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
            True,
        ),
        (
            "inspection_failed",
            DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
            True,
        ),
    ],
)
async def test_provider_failures_never_degrade_to_worker_lost(
    tmp_path,
    runner_code: str,
    expected: DownloadErrorCode,
    retryable: bool,
) -> None:
    case = fixture(artifact(tmp_path))
    case.runner.error = MediaRunnerClientError(runner_code, 422)

    assert await case.execution.execute(case.job_id) is ExecutionDisposition.ACK

    assert case.repository.failure["error_code"] == expected.value
    assert case.repository.failure["retryable"] is retryable


@pytest.mark.asyncio
async def test_duplicate_and_hash_mismatch_are_idempotent(tmp_path) -> None:
    duplicate = fixture(artifact(tmp_path / "duplicate"))
    duplicate.repository.claimed = False
    duplicate.repository.status = "succeeded"
    assert await duplicate.execution.execute(duplicate.job_id) is (
        ExecutionDisposition.ACK
    )
    assert duplicate.runner.download_arguments is None

    mismatch_artifact = artifact(tmp_path / "mismatch")
    mismatch_artifact = replace(mismatch_artifact, sha256="0" * 64)
    mismatch = fixture(mismatch_artifact)
    assert await mismatch.execution.execute(mismatch.job_id) is (
        ExecutionDisposition.ACK
    )
    assert mismatch.repository.failure["error_code"] == (
        DownloadErrorCode.MEDIA_VALIDATION_FAILED.value
    )
    assert (
        mismatch.repository.failure["error_message"] == "artifact digest does not match"
    )
    assert mismatch.storage.uploads == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("cancelled", ExecutionDisposition.ACK),
        ("queued", ExecutionDisposition.REQUEUE),
    ],
)
async def test_cancel_or_lease_loss_cancels_runner(tmp_path, status, expected) -> None:
    case = fixture(artifact(tmp_path / status))
    case.runner.block = True
    case.repository.heartbeat_results = [False]
    case.repository.status = status

    assert await case.execution.execute(case.job_id) is expected
    assert case.runner.cancelled == 1
    assert case.cleaner.calls
