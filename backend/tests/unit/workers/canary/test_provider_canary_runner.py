from __future__ import annotations

from pathlib import Path

import pytest
from app.integrations.media_runner_models import MediaRunnerClientError, RunnerArtifact
from app.services.downloads.errors import (
    MediaInspectionAuthRequired,
    MediaInspectionGuestContextRequired,
)
from app.services.downloads.inspection_models import RunnerInspection
from app.services.provider_types import ProviderAccessContextRef, ProviderAccessMode
from app.workers.canary.runner import ProviderCanaryRunner

URL = "https://www.youtube.com/watch?v=owned"


class FakeClient:
    def __init__(
        self, access_mode: ProviderAccessMode, provider_key: str = "youtube"
    ) -> None:
        self.access_context = context(access_mode, provider_key)
        self.downloaded: list[str] = []
        self.error: Exception | None = None
        self.inspected: list[str] = []
        self.closed = False

    async def inspect(self, url: str) -> RunnerInspection:
        self.inspected.append(url)
        if self.error is not None:
            raise self.error
        return RunnerInspection(
            extractor_key="Youtube",
            provider_media_id="owned",
            title="Owned",
            duration_seconds=30,
            formats=(),
            access_context=self.access_context,
        )

    async def context(self, _url: str) -> ProviderAccessContextRef:
        return self.access_context

    async def download(self, task_id: str, *_args, **_kwargs) -> RunnerArtifact:
        self.downloaded.append(task_id)
        return RunnerArtifact(
            task_id=task_id,
            workspace=Path("/work") / task_id,
            artifact=Path("/work") / task_id / "artifact.mp4",
            size_bytes=1,
            sha256="a" * 64,
            duration_seconds=30,
            container="mp4",
            video_streams=1,
            audio_streams=1,
        )

    async def status(self, _task_id: str) -> None:
        raise AssertionError("not used")

    async def cancel(self, _task_id: str) -> None:
        raise AssertionError("not used")

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_anonymous_failure_and_operator_success_remain_separate() -> None:
    anonymous = FakeClient(ProviderAccessMode.ANONYMOUS)
    anonymous.error = MediaInspectionAuthRequired()
    operator = FakeClient(ProviderAccessMode.OPERATOR_MANAGED)
    runner = ProviderCanaryRunner(anonymous, operator)  # type: ignore[arg-type]

    with pytest.raises(MediaInspectionAuthRequired) as captured:
        await runner.inspect(URL, access_mode=ProviderAccessMode.ANONYMOUS)
    operator_result = await runner.inspect(
        URL,
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
    )

    assert captured.value.access_mode is ProviderAccessMode.ANONYMOUS
    assert anonymous.inspected == [URL]
    assert operator.inspected == [URL]
    assert (
        operator_result.access_context.access_mode
        is ProviderAccessMode.OPERATOR_MANAGED
    )


@pytest.mark.asyncio
async def test_missing_operator_is_attributed_to_operator_route() -> None:
    anonymous = FakeClient(ProviderAccessMode.ANONYMOUS)
    runner = ProviderCanaryRunner(anonymous)  # type: ignore[arg-type]

    with pytest.raises(MediaInspectionAuthRequired) as captured:
        await runner.inspect(URL, access_mode=ProviderAccessMode.OPERATOR_MANAGED)

    assert captured.value.access_mode is ProviderAccessMode.OPERATOR_MANAGED
    assert anonymous.inspected == []


def context(
    access_mode: ProviderAccessMode, provider_key: str = "youtube"
) -> ProviderAccessContextRef:
    material = access_mode is not ProviderAccessMode.ANONYMOUS
    return ProviderAccessContextRef(
        provider_key=provider_key,
        profile_version="youtube" if provider_key == "youtube" else "default",
        access_mode=access_mode,
        credential_version_id="version-1" if material else None,
        egress_affinity_id="default",
        client_profile_id="yt-dlp-default",
        attestation_provider_version=None,
        engine_commit="5d6b8c8",
        runtime_revision="a" * 64,
    )


@pytest.mark.asyncio
async def test_guest_context_inspection_and_media_never_use_account_or_anonymous() -> (
    None
):
    anonymous = FakeClient(ProviderAccessMode.ANONYMOUS)
    operator = FakeClient(ProviderAccessMode.OPERATOR_MANAGED, "douyin")
    guest = FakeClient(ProviderAccessMode.GUEST, "douyin")
    runner = ProviderCanaryRunner(anonymous, operator, guests={"douyin": guest})  # type: ignore[arg-type]
    url = "https://www.douyin.com/video/7674644830270473609"
    assert (
        await runner.context(url, access_mode=ProviderAccessMode.GUEST)
        == guest.access_context
    )
    result = await runner.inspect(url, access_mode=ProviderAccessMode.GUEST)
    assert result.access_context == guest.access_context
    await runner.download(
        "guest_probe",
        url,
        None,
        expected_provider_media_id="owned",
        expected_extractor_key="Douyin",
        access_context=result.access_context,
    )
    assert guest.inspected == [url]
    assert guest.downloaded == ["guest_probe"]
    assert not operator.inspected and not operator.downloaded
    assert not anonymous.inspected and not anonymous.downloaded
    await runner.close()
    assert guest.closed and operator.closed and anonymous.closed


@pytest.mark.asyncio
async def test_missing_guest_does_not_fall_back_to_a_configured_account() -> None:
    anonymous = FakeClient(ProviderAccessMode.ANONYMOUS)
    operator = FakeClient(ProviderAccessMode.OPERATOR_MANAGED, "douyin")
    runner = ProviderCanaryRunner(anonymous, operator)  # type: ignore[arg-type]
    url = "https://www.douyin.com/video/7674644830270473609"
    for operation in (runner.context, runner.inspect):
        with pytest.raises(MediaInspectionGuestContextRequired) as captured:
            await operation(url, access_mode=ProviderAccessMode.GUEST)
        assert captured.value.access_mode is ProviderAccessMode.GUEST
    with pytest.raises(MediaRunnerClientError) as captured_download:
        await runner.download(
            "guest_probe",
            url,
            None,
            expected_provider_media_id="owned",
            expected_extractor_key="Douyin",
            access_context=context(ProviderAccessMode.GUEST, "douyin"),
        )
    assert captured_download.value.code == "guest_context_required"
    assert not operator.inspected and not operator.downloaded
    assert not anonymous.inspected and not anonymous.downloaded
