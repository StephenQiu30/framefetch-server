from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from app.integrations.media_runner import MediaRunnerRouter
from app.integrations.media_runner_models import MediaRunnerClientError, RunnerArtifact
from app.services.downloads.errors import (
    MediaInspectionTemporarilyUnavailable,
)
from app.services.downloads.inspection_models import RunnerInspection
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_types import ProviderAccessContextRef, ProviderAccessMode


class FakeClient:
    def __init__(self, context: ProviderAccessContextRef) -> None:
        self.frozen = context
        self.inspect_error: Exception | None = None
        self.download_error: Exception | None = None
        self.inspected: list[str] = []
        self.downloaded: list[str] = []
        self.context_requests: list[tuple[str, ...]] = []

    async def context(self, url: str, *, access_mode=None) -> ProviderAccessContextRef:
        self.context_requests.append((url,))
        return self.frozen

    async def contexts_for_providers(
        self, provider_keys: tuple[str, ...], *, access_mode=None
    ) -> tuple[ProviderAccessContextRef, ...]:
        self.context_requests.append(provider_keys)
        return (self.frozen,)

    async def inspect(self, url: str) -> RunnerInspection:
        self.inspected.append(url)
        if self.inspect_error is not None:
            raise self.inspect_error
        return RunnerInspection(
            extractor_key="Youtube",
            provider_media_id="owned",
            title="Owned",
            duration_seconds=30,
            formats=(),
            access_context=self.frozen,
        )

    async def download(self, task_id: str, *_args, **_kwargs) -> RunnerArtifact:
        self.downloaded.append(task_id)
        if self.download_error is not None:
            raise self.download_error
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

    async def status(self, _task_id):
        raise AssertionError("not used")

    async def cancel(self, _task_id):
        raise AssertionError("not used")

    async def close(self) -> None:
        return None


class AlwaysSession:
    async def policy_for(self, url):
        return ProviderAccessPolicy.OPERATOR_PUBLIC

    async def ensure_ready(self, url):
        return None


async def test_inspect_and_download_use_only_session():
    client = FakeClient(context(ProviderAccessMode.OPERATOR_MANAGED))
    router = MediaRunnerRouter(client, session_routes=AlwaysSession())
    result = await router.inspect("https://youtube.com/watch?v=owned")
    assert result.access_context == client.frozen
    await router.download(
        "task",
        "https://youtube.com/watch?v=owned",
        None,
        expected_provider_media_id="owned",
        expected_extractor_key="Youtube",
        access_context=client.frozen,
    )
    assert client.inspected == ["https://youtube.com/watch?v=owned"]
    assert client.downloaded == ["task"]


@pytest.mark.parametrize("mode", [ProviderAccessMode.GUEST])
async def test_retired_guest_context_is_rejected_without_execution(mode):
    client = FakeClient(context(ProviderAccessMode.OPERATOR_MANAGED))
    router = MediaRunnerRouter(client, session_routes=AlwaysSession())
    with pytest.raises(MediaRunnerClientError):
        await router.download(
            "task",
            "https://youtube.com/watch?v=owned",
            None,
            expected_provider_media_id="owned",
            expected_extractor_key="Youtube",
            access_context=context(mode),
        )
    assert client.downloaded == []


async def test_session_failure_is_authoritative_and_not_retried():
    client = FakeClient(context(ProviderAccessMode.OPERATOR_MANAGED))
    client.inspect_error = MediaInspectionTemporarilyUnavailable()
    router = MediaRunnerRouter(client, session_routes=AlwaysSession())
    with pytest.raises(MediaInspectionTemporarilyUnavailable) as failure:
        await router.inspect("https://youtube.com/watch?v=owned")
    assert failure.value.access_mode is ProviderAccessMode.OPERATOR_MANAGED
    assert len(client.inspected) == 1


async def test_context_batch_isolates_failed_sites():
    class Client(FakeClient):
        async def contexts_for_providers(self, keys, *, access_mode=None):
            if "youtube" in keys:
                raise MediaRunnerClientError("provider_session_not_ready", 503)
            return tuple(replace(self.frozen, provider_key=key) for key in keys)

    client = Client(context(ProviderAccessMode.OPERATOR_MANAGED))
    router = MediaRunnerRouter(client, session_routes=AlwaysSession())
    resolved = await router.contexts_for_providers(
        {
            "youtube": ProviderAccessMode.OPERATOR_MANAGED,
            "douyin": ProviderAccessMode.OPERATOR_MANAGED,
            "generic": ProviderAccessMode.ANONYMOUS,
        }
    )
    assert set(resolved) == {"douyin"}


def context(
    mode: ProviderAccessMode, provider: str = "youtube"
) -> ProviderAccessContextRef:
    stateful = mode is not ProviderAccessMode.ANONYMOUS
    return ProviderAccessContextRef(
        provider_key=provider if stateful else "generic",
        profile_version=provider if stateful else "default",
        access_mode=mode,
        credential_version_id="browser" if stateful else None,
        egress_affinity_id=f"provider:{provider}" if stateful else "default",
        client_profile_id="yt-dlp-default",
        attestation_provider_version=None,
        engine_commit="5d6b8c8",
        runtime_revision="a" * 64,
    )


async def test_anonymous_youtube_inspection_and_download_stay_anonymous():
    frozen = replace(
        context(ProviderAccessMode.ANONYMOUS),
        provider_key="youtube",
        profile_version="youtube",
    )
    client = FakeClient(frozen)
    router = MediaRunnerRouter(client, session_routes=AlwaysSession())
    inspected = await router.inspect("https://youtube.com/watch?v=owned")
    assert inspected.access_context == frozen
    await router.download(
        "task",
        "https://youtube.com/watch?v=owned",
        None,
        expected_provider_media_id="owned",
        expected_extractor_key="Youtube",
        access_context=frozen,
    )
    assert client.downloaded == ["task"]
