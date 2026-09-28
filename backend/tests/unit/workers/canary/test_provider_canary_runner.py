from __future__ import annotations

from pathlib import Path

import pytest
from app.integrations.media_runner_models import RunnerArtifact
from app.services.downloads.errors import (
    MediaInspectionAuthRequired,
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


@pytest.mark.parametrize(
    "mode", [ProviderAccessMode.ANONYMOUS, ProviderAccessMode.GUEST]
)
async def test_retired_modes_never_reach_canary_client(mode):
    client = FakeClient(ProviderAccessMode.OPERATOR_MANAGED)
    runner = ProviderCanaryRunner(client)
    for operation in (runner.context, runner.inspect):
        with pytest.raises(MediaInspectionAuthRequired):
            await operation(URL, access_mode=mode)
    assert not client.inspected


async def test_canary_session_error_and_success_are_authoritative():
    client = FakeClient(ProviderAccessMode.OPERATOR_MANAGED)
    runner = ProviderCanaryRunner(client)
    client.error = MediaInspectionAuthRequired()
    with pytest.raises(MediaInspectionAuthRequired) as captured:
        await runner.inspect(URL, access_mode=ProviderAccessMode.OPERATOR_MANAGED)
    assert captured.value.access_mode is ProviderAccessMode.OPERATOR_MANAGED
    client.error = None
    assert (
        await runner.inspect(URL, access_mode=ProviderAccessMode.OPERATOR_MANAGED)
    ).access_context == client.access_context
    await runner.close()
    assert client.closed


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
