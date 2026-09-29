from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest
from app.integrations.media_runner import MediaRunnerHttpClient, _retry_after
from app.integrations.media_runner_models import MediaRunnerClientError
from app.services.downloads.errors import (
    MediaInspectionAuthRequired,
    MediaInspectionConfigurationMissing,
    MediaInspectionDurationLimitExceeded,
    MediaInspectionFailure,
    MediaInspectionLinkUnavailable,
    MediaInspectionMediaUnsupported,
    MediaInspectionSessionNotReady,
    MediaInspectionTemporarilyUnavailable,
    MediaInspectionTimeout,
    MediaInspectionUnsupported,
)
from app.services.provider_route_admission import (
    ProviderRouteAdmission,
    ProviderRouteLease,
)
from app.services.provider_types import ProviderAccessContextRef, ProviderAccessMode
from app.workers.runner.contracts import DownloadPlanContract


def test_retry_after_parses_seconds_dates_and_rejects_malformed_values():
    before = datetime.now(UTC)
    numeric = _retry_after("600")
    assert numeric is not None and 600 <= (numeric - before).total_seconds() < 601
    assert _retry_after(format_datetime(numeric)) is not None
    for invalid in ("-1", "NaN", "infinity", "9" * 200, "tomorrow", None):
        assert _retry_after(invalid) is None


@pytest.mark.asyncio
async def test_context_reads_the_runner_runtime_generation() -> None:
    expected = _access_context()

    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/context"
        assert json.loads(request.content) == {"url": "https://media.example/video"}
        return httpx.Response(200, json=expected.to_document())

    http = httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.MockTransport(respond),
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
    )

    context = await client.context("https://media.example/video")

    assert context == expected
    await http.aclose()


@pytest.mark.asyncio
async def test_new_client_fails_closed_against_pre_revision_runner() -> None:
    old_document = _access_context().to_document()
    old_document.pop("runtime_revision")

    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=old_document)

    http = httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
    )

    with pytest.raises(MediaRunnerClientError) as caught:
        await client.context("https://media.example/video")

    assert caught.value.code == "runner_release_mismatch"
    await http.aclose()


@pytest.mark.asyncio
async def test_context_batch_uses_one_short_lived_runner_request() -> None:
    expected = _access_context()

    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/contexts"
        assert json.loads(request.content) == {"provider_keys": ["generic"]}
        assert request.extensions["timeout"]["read"] == 0.25
        return httpx.Response(200, json={"contexts": [expected.to_document()]})

    http = httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.MockTransport(respond),
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=30,
        download_timeout_seconds=30,
        client=http,
    )

    contexts = await client.contexts_for_providers(("generic",))

    assert contexts == (expected,)
    await http.aclose()


@pytest.mark.asyncio
async def test_context_batch_rejects_a_semantically_invalid_runner_context() -> None:
    invalid = {
        **_access_context().to_document(),
        "access_mode": "operator_managed",
        "credential_version_id": None,
    }

    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"contexts": [invalid]})

    http = httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.MockTransport(respond),
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=30,
        download_timeout_seconds=30,
        client=http,
    )

    with pytest.raises(MediaRunnerClientError) as captured:
        await client.contexts_for_providers(("generic",))

    assert captured.value.code == "invalid_runner_response"
    await http.aclose()


@pytest.mark.asyncio
async def test_inspect_exposes_provider_access_requirement() -> None:
    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "error": {
                    "code": "credential_required",
                    "message": "provider access required",
                }
            },
        )

    http = httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.MockTransport(respond),
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
    )

    with pytest.raises(MediaInspectionAuthRequired):
        await client.inspect("https://www.douyin.com/video/123")

    await http.aclose()


@pytest.mark.asyncio
async def test_operator_source_missing_is_deployment_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def context(_url: str) -> ProviderAccessContextRef:
        raise MediaRunnerClientError("credential_required", 422)

    http = httpx.AsyncClient(base_url="http://runner")
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        expected_access_mode=ProviderAccessMode.OPERATOR_MANAGED,
        client=http,
    )
    monkeypatch.setattr(client, "context", context)

    with pytest.raises(MediaInspectionConfigurationMissing):
        await client.inspect("https://www.youtube.com/watch?v=jNQXAC9IVRw")

    await http.aclose()


@pytest.mark.asyncio
async def test_operator_content_auth_requirement_stays_content_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def context(_url: str) -> ProviderAccessContextRef:
        return _access_context()

    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={"error": {"code": "credential_required", "message": "required"}},
        )

    http = httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        expected_access_mode=ProviderAccessMode.OPERATOR_MANAGED,
        client=http,
    )
    monkeypatch.setattr(client, "context", context)

    with pytest.raises(MediaInspectionAuthRequired):
        await client.inspect("https://www.youtube.com/watch?v=jNQXAC9IVRw")

    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("context_ready", (False, True))
@pytest.mark.parametrize(
    "code", ("provider_session_not_ready", "provider_session_unavailable")
)
async def test_inspect_exposes_a_site_session_that_is_not_ready(
    monkeypatch: pytest.MonkeyPatch, context_ready: bool, code: str
) -> None:
    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"code": code, "message": code}})

    http = httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
        expected_access_mode=ProviderAccessMode.OPERATOR_MANAGED,
    )

    async def context(_url: str) -> ProviderAccessContextRef:
        if not context_ready:
            raise MediaRunnerClientError(code, 503)
        return _access_context()

    monkeypatch.setattr(client, "context", context)
    with pytest.raises(MediaInspectionSessionNotReady) as captured:
        await client.inspect("https://www.douyin.com/video/123")
    assert captured.value.before_media_io is not context_ready
    await http.aclose()


@pytest.mark.asyncio
async def test_inspect_exposes_duration_safety_boundary() -> None:
    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "error": {
                    "code": "duration_limit_exceeded",
                    "message": "duration limit exceeded",
                }
            },
        )

    http = httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.MockTransport(respond),
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
    )

    with pytest.raises(MediaInspectionDurationLimitExceeded):
        await client.inspect("https://x.com/example/status/123")

    await http.aclose()


@pytest.mark.asyncio
async def test_inspect_exposes_unavailable_provider_link() -> None:
    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "error": {
                    "code": "provider_link_unavailable",
                    "message": "provider link unavailable",
                }
            },
        )

    http = httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.MockTransport(respond),
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
    )

    with pytest.raises(MediaInspectionLinkUnavailable):
        await client.inspect("https://v.douyin.com/KWku50HECg/")

    await http.aclose()


@pytest.mark.asyncio
async def test_inspect_exposes_unsupported_provider() -> None:
    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "error": {
                    "code": "provider_unsupported",
                    "message": "provider unsupported",
                }
            },
        )

    http = httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.MockTransport(respond),
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
    )

    with pytest.raises(MediaInspectionUnsupported):
        await client.inspect("https://weixin.qq.com/sph/AFWYoXF5Bw")

    await http.aclose()


@pytest.mark.asyncio
async def test_inspect_exposes_unsupported_provider_media() -> None:
    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "error": {
                    "code": "provider_media_unsupported",
                    "message": "provider media unsupported",
                }
            },
        )

    http = httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.MockTransport(respond),
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
    )

    with pytest.raises(MediaInspectionMediaUnsupported):
        await client.inspect("https://www.facebook.com/share/p/example/")

    await http.aclose()


@pytest.mark.asyncio
async def test_inspect_maps_unsupported_source() -> None:
    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "error": {
                    "code": "unsupported_source",
                    "message": "unsupported source",
                }
            },
        )

    http = httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.MockTransport(respond),
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
    )

    with pytest.raises(MediaInspectionMediaUnsupported):
        await client.inspect("https://www.youtube.com/watch?v=owned")

    await http.aclose()


@pytest.mark.asyncio
async def test_inspect_exposes_runner_timeout_response() -> None:
    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            504,
            json={"error": {"code": "inspection_timeout", "message": "timeout"}},
        )

    http = httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.MockTransport(respond),
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
    )

    with pytest.raises(MediaInspectionTimeout):
        await client.inspect("https://www.douyin.com/video/123")

    await http.aclose()


@pytest.mark.asyncio
async def test_inspect_exposes_client_read_timeout() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("runner timed out", request=request)

    http = httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.MockTransport(respond),
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
    )

    with pytest.raises(MediaInspectionTimeout):
        await client.inspect("https://www.douyin.com/video/123")

    await http.aclose()


@pytest.mark.asyncio
async def test_inspect_classifies_runner_disconnect_as_dependency_unavailable() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("runner unavailable", request=request)

    http = httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.MockTransport(respond),
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=Path("."),
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
    )

    with pytest.raises(MediaInspectionFailure) as caught:
        await client.inspect("https://www.douyin.com/video/123")

    assert type(caught.value) is MediaInspectionTemporarilyUnavailable
    await http.aclose()


@pytest.mark.asyncio
async def test_download_sends_expected_inspection_identity(tmp_path) -> None:
    captured: dict[str, object] = {}
    workspace = tmp_path / "job-controlled"

    async def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "task_id": "job_123",
                "workspace_path": str(workspace),
                "artifact": {
                    "relative_path": "artifact.mp4",
                    "size_bytes": 5,
                    "sha256": "a" * 64,
                    "duration_seconds": 30,
                    "container": "mp4",
                    "video_streams": 1,
                    "audio_streams": 1,
                },
                "selection": None,
            },
        )

    http = httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.MockTransport(respond),
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=tmp_path,
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
    )
    plan = DownloadPlanContract.model_validate(
        {
            "height": 720,
            "width": 1280,
            "fps_bucket": "fps_30",
            "dynamic_range": "sdr",
            "video_codec_family": "h264",
            "audio_codec_family": "aac",
            "audio_language": None,
            "container_preference": "mp4",
            "compatibility_profile": "balanced",
            "hints": {"video_id": "video-id", "audio_id": "a1"},
        }
    ).to_domain()

    await client.download(
        "job_123",
        "https://media.example/video",
        plan,
        expected_provider_media_id="video-1",
        expected_extractor_key="Controlled",
        access_context=_access_context(),
    )

    assert captured["expected_provider_media_id"] == "video-1"
    assert captured["expected_extractor_key"] == "Controlled"
    assert captured["access_context"] == _access_context().to_document()
    await http.aclose()


@pytest.mark.asyncio
async def test_new_client_rejects_legacy_probe_revision(tmp_path: Path) -> None:
    newer = replace(_access_context(), runtime_revision="a" * 64)
    returned = _access_context().to_document()
    returned.pop("runtime_revision")

    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/inspect"
        assert json.loads(request.content)["access_context"] == newer.to_document()
        return httpx.Response(
            200,
            json={
                "media": {
                    "provider_media_id": "video-1",
                    "title": "Video",
                    "duration_seconds": 30,
                    "extractor_key": "Controlled",
                },
                "streams": [],
                "options": [{"option_id": "one", "label": "720p"}],
                "access_context": returned,
            },
        )

    http = httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=tmp_path,
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
    )
    with pytest.raises(MediaRunnerClientError) as captured:
        await client._inspect_response("https://media.example/video", newer)
    assert captured.value.code == "runner_release_mismatch"
    returned["engine_commit"] = "different"
    with pytest.raises(MediaRunnerClientError) as captured:
        await client._inspect_response("https://media.example/video", newer)
    assert captured.value.code == "runner_release_mismatch"
    await http.aclose()


@pytest.mark.asyncio
async def test_new_client_half_open_download_rejects_legacy_runner(
    tmp_path: Path,
) -> None:
    newer = replace(_access_context(), runtime_revision="a" * 64)
    events: list[str] = []

    class HalfOpen:
        def __init__(self) -> None:
            self.probing = True

        async def acquire(self, key, owner):
            return ProviderRouteLease(
                key,
                owner,
                1 if self.probing else None,
                datetime.now(UTC).replace(year=datetime.now(UTC).year + 1),
            )

        async def finish(self, _lease, *, success, **_kwargs):
            assert not success
            self.probing = False

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/inspect":
            events.append("probe")
            return httpx.Response(
                200,
                json={
                    "media": {
                        "provider_media_id": "video-1",
                        "title": "Video",
                        "duration_seconds": 30,
                        "extractor_key": "Controlled",
                    },
                    "streams": [],
                    "options": [{"option_id": "one", "label": "gallery"}],
                    "access_context": {
                        key: value
                        for key, value in _access_context().to_document().items()
                        if key != "runtime_revision"
                    },
                },
            )
        events.append("download")
        return httpx.Response(
            200,
            json={
                "task_id": "job_123",
                "workspace_path": str(tmp_path / "job-controlled"),
                "artifact": {
                    "relative_path": "artifact.zip",
                    "size_bytes": 5,
                    "sha256": "a" * 64,
                    "duration_seconds": 30,
                    "container": "zip",
                    "video_streams": 0,
                    "audio_streams": 0,
                    "media_kind": "image_gallery",
                    "asset_count": 1,
                },
                "selection": None,
            },
        )

    http = httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    )
    client = MediaRunnerHttpClient(
        base_url="http://runner",
        secret=b"s" * 32,
        workspace_root=tmp_path,
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
        admission=ProviderRouteAdmission(HalfOpen()),  # type: ignore[arg-type]
    )
    with pytest.raises(MediaRunnerClientError) as captured:
        await client.download(
            "job_123",
            "https://media.example/video",
            None,
            expected_provider_media_id="video-1",
            expected_extractor_key="Controlled",
            access_context=newer,
            media_kind="image_gallery",  # type: ignore[arg-type]
            asset_count=1,
        )
    assert captured.value.code == "runner_release_mismatch"
    assert events == ["probe"]
    await http.aclose()


def _access_context() -> ProviderAccessContextRef:
    return ProviderAccessContextRef(
        provider_key="generic",
        profile_version="1",
        access_mode=ProviderAccessMode.ANONYMOUS,
        credential_version_id=None,
        egress_affinity_id="default",
        client_profile_id="yt-dlp-default",
        attestation_provider_version=None,
        engine_commit="5d6b8c8",
        runtime_revision="a" * 64,
    )
