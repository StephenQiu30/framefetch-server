from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.services.downloads.errors import (
    ApplicationError,
    ApplicationErrorCode,
    MediaInspectionAuthRequired,
    MediaInspectionDurationLimitExceeded,
    MediaInspectionLinkUnavailable,
    MediaInspectionUnsupported,
)
from app.services.downloads.fingerprints import HmacRequestFingerprinter
from app.services.downloads.inspect_media import InspectMedia
from app.services.downloads.inspection_models import RunnerFormat, RunnerInspection
from app.services.downloads.queries import GetInspection
from app.services.downloads.rules.enums import (
    AudioCodecFamily,
    CompatibilityProfile,
    ContainerPreference,
    DynamicRange,
    FpsBucket,
    VideoCodecFamily,
)
from app.services.downloads.rules.formats import DownloadPlan, ProviderHints
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_types import ProviderAccessContextRef, ProviderAccessMode
from tests.unit.services.fakes import (
    FakeCipher,
    FakeRepository,
    FakeRunner,
    FakeValidator,
)

NOW = datetime(2026, 8, 6, 9, tzinfo=UTC)
URL = "https://media.example/watch?v=owned"
OWNER = "a" * 64


def plan(height: int = 1080) -> DownloadPlan:
    return DownloadPlan(
        height=height,
        width=1920 if height == 1080 else 1280,
        fps_bucket=FpsBucket.FPS_30,
        dynamic_range=DynamicRange.SDR,
        video_codec_family=VideoCodecFamily.H264,
        audio_codec_family=AudioCodecFamily.AAC,
        audio_language="zh-CN",
        container_preference=ContainerPreference.MP4,
        compatibility_profile=CompatibilityProfile.BALANCED,
        hints=ProviderHints(video_id="137", audio_id="140"),
    )


def runner_result(*, duration: int = 30) -> RunnerInspection:
    return RunnerInspection(
        extractor_key="Controlled",
        provider_media_id="video-1",
        title="Owned video",
        duration_seconds=duration,
        formats=(RunnerFormat("1080p MP4", plan()),),
        access_context=access_context(),
        thumbnail_data_url="data:image/avif;base64,Y292ZXI=",
    )


def use_case(
    repository: FakeRepository,
    result: RunnerInspection,
) -> tuple[InspectMedia, FakeRunner, FakeCipher]:
    runner, cipher = FakeRunner(result), FakeCipher()
    return (
        InspectMedia(
            repository=repository,
            runner=runner,
            url_validator=FakeValidator(),
            url_cipher=cipher,
            fingerprinter=HmacRequestFingerprinter(b"k" * 32),
            now=lambda: NOW,
            new_id=uuid4,
            inspection_ttl=timedelta(minutes=15),
            max_duration_seconds=7_200,
        ),
        runner,
        cipher,
    )


@pytest.mark.asyncio
async def test_inspect_encrypts_url_and_returns_only_semantic_formats() -> None:
    repository = FakeRepository()
    inspect, runner, cipher = use_case(repository, runner_result())

    view = await inspect(URL, OWNER, "inspect-1")

    command = repository.inspection_commands[0]
    assert command.expires_at == NOW + timedelta(minutes=15)
    assert command.url_ciphertext == b"opaque-ciphertext"
    assert URL.encode() not in command.url_ciphertext
    assert runner.seen == cipher.seen == [URL]
    assert not hasattr(command, "url")
    assert not hasattr(view, "url")
    assert URL not in repr(command)
    assert view.formats[0].plan.hints == ProviderHints()
    assert command.formats[0].provider_hints == {
        "video_id": "137",
        "audio_id": "140",
    }
    assert command.metadata == {
        "access_policy_id": "public",
        "provider_access_context": access_context().to_document(),
        "thumbnail_url": "data:image/avif;base64,Y292ZXI=",
    }
    assert view.thumbnail_url == f"/api/inspections/{view.id}/thumbnail"


@pytest.mark.asyncio
async def test_inspection_idempotency_replays_and_conflicts() -> None:
    repository = FakeRepository()
    inspect, _, _ = use_case(repository, runner_result())
    first = await inspect(URL, OWNER, "same-key")
    replay = await inspect(URL, OWNER, "same-key")

    assert replay.id == first.id
    with pytest.raises(ApplicationError) as caught:
        await inspect("https://other.example/video", OWNER, "same-key")
    assert caught.value.code is ApplicationErrorCode.IDEMPOTENCY_CONFLICT


async def test_inspection_policy_is_frozen_and_part_of_idempotency() -> None:
    repository = FakeRepository()
    inspect, _, _ = use_case(repository, runner_result())
    first = await inspect(
        URL, OWNER, "policy-key", access_policy=ProviderAccessPolicy.PUBLIC
    )
    replay = await inspect(
        URL, OWNER, "policy-key", access_policy=ProviderAccessPolicy.PUBLIC
    )
    assert first.id == replay.id
    assert first.access_policy_id is ProviderAccessPolicy.PUBLIC
    with pytest.raises(ApplicationError) as caught:
        await inspect(
            URL, OWNER, "policy-key", access_policy=ProviderAccessPolicy.OPERATOR_PUBLIC
        )
    assert caught.value.code is ApplicationErrorCode.IDEMPOTENCY_CONFLICT


@pytest.mark.asyncio
async def test_invalid_url_never_reaches_runner() -> None:
    repository = FakeRepository()
    inspect, runner, _ = use_case(repository, runner_result())
    unsafe_url = "file:///etc/passwd"

    with pytest.raises(ApplicationError) as caught:
        await inspect(unsafe_url, OWNER, "inspect-1")

    assert caught.value.code is ApplicationErrorCode.INVALID_URL
    assert unsafe_url not in str(caught.value)
    assert runner.seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "decision", "reason"),
    (
        (
            "https://v.qq.com/channel/cartoon",
            "unsupported",
            "unsupported_qqvideo_url",
        ),
        (
            "https://mp.weixin.qq.com/s/AbCdEf123",
            "blocked",
            "article_discovery_required",
        ),
    ),
)
async def test_restricted_platform_returns_persisted_inspection_without_runner(
    url: str,
    decision: str,
    reason: str,
) -> None:
    repository = FakeRepository()
    inspect, runner, cipher = use_case(repository, runner_result())

    view = await inspect(url, OWNER, "restricted-source")

    assert runner.seen == []
    assert cipher.seen == [url]
    assert view.duration_seconds == 0
    assert view.formats == ()
    assert view.access_decision.value == decision
    assert view.restriction_reason == reason
    assert repository.inspection_commands[0].formats == ()


@pytest.mark.asyncio
async def test_wechat_channels_public_share_reaches_provider_runner() -> None:
    repository = FakeRepository()
    inspect, runner, cipher = use_case(repository, runner_result())
    url = "https://weixin.qq.com/sph/AbCdEf12"

    view = await inspect(url, OWNER, "wechat-channels-public")

    assert runner.seen == cipher.seen == [url]
    assert view.access_decision.value == "downloadable"
    assert len(view.formats) == 1


@pytest.mark.asyncio
async def test_duration_limit_and_empty_formats_are_rejected() -> None:
    repository = FakeRepository()
    too_long, _, _ = use_case(repository, runner_result(duration=7_201))
    with pytest.raises(ApplicationError) as duration_error:
        await too_long(URL, OWNER, "duration")
    assert duration_error.value.code is ApplicationErrorCode.DURATION_LIMIT_EXCEEDED

    empty_result = RunnerInspection(
        "Controlled",
        "id",
        "title",
        30,
        (),
        access_context(),
    )
    no_formats, _, _ = use_case(repository, empty_result)
    with pytest.raises(ApplicationError) as format_error:
        await no_formats(URL, OWNER, "formats")
    assert format_error.value.code is ApplicationErrorCode.FORMAT_UNAVAILABLE
    assert repository.inspection_commands == []


@pytest.mark.asyncio
async def test_runner_duration_boundary_keeps_provider_support_distinct() -> None:
    class DurationRejectedRunner(FakeRunner):
        async def inspect(
            self, _url: str, *, access_policy: ProviderAccessPolicy
        ) -> RunnerInspection:
            raise MediaInspectionDurationLimitExceeded

    inspect = InspectMedia(
        repository=FakeRepository(),
        runner=DurationRejectedRunner(runner_result()),
        url_validator=FakeValidator(),
        url_cipher=FakeCipher(),
        fingerprinter=HmacRequestFingerprinter(b"k" * 32),
        now=lambda: NOW,
        new_id=uuid4,
        inspection_ttl=timedelta(minutes=15),
        max_duration_seconds=86_400,
    )

    with pytest.raises(ApplicationError) as caught:
        await inspect(URL, OWNER, "duration-from-runner")

    assert caught.value.code is ApplicationErrorCode.DURATION_LIMIT_EXCEEDED


@pytest.mark.asyncio
async def test_provider_access_requirement_is_reported_explicitly() -> None:
    repository = FakeRepository()
    inspect, runner, _ = use_case(repository, runner_result())
    runner.inspect = _raise_provider_access  # type: ignore[method-assign]

    with pytest.raises(ApplicationError) as caught:
        await inspect(URL, OWNER, "provider-access")

    assert caught.value.code is ApplicationErrorCode.PROVIDER_AUTH_REQUIRED


@pytest.mark.asyncio
async def test_unavailable_provider_link_is_reported_explicitly() -> None:
    repository = FakeRepository()
    inspect, runner, _ = use_case(repository, runner_result())
    runner.inspect = _raise_provider_link_unavailable  # type: ignore[method-assign]

    with pytest.raises(ApplicationError) as caught:
        await inspect(URL, OWNER, "provider-link-unavailable")

    assert caught.value.code is ApplicationErrorCode.PROVIDER_LINK_UNAVAILABLE


@pytest.mark.asyncio
async def test_unsupported_provider_is_reported_explicitly() -> None:
    repository = FakeRepository()
    inspect, runner, _ = use_case(repository, runner_result())
    runner.inspect = _raise_provider_unsupported  # type: ignore[method-assign]

    with pytest.raises(ApplicationError) as caught:
        await inspect(URL, OWNER, "provider-unsupported")

    assert caught.value.code is ApplicationErrorCode.PROVIDER_UNSUPPORTED


async def _raise_provider_access(
    _: str, *, access_policy: ProviderAccessPolicy
) -> RunnerInspection:
    raise MediaInspectionAuthRequired


async def _raise_provider_link_unavailable(
    _: str, *, access_policy: ProviderAccessPolicy
) -> RunnerInspection:
    raise MediaInspectionLinkUnavailable


async def _raise_provider_unsupported(
    _: str, *, access_policy: ProviderAccessPolicy
) -> RunnerInspection:
    raise MediaInspectionUnsupported


def access_context() -> ProviderAccessContextRef:
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


@pytest.mark.asyncio
async def test_get_inspection_keeps_expired_metadata_readable() -> None:
    repository = FakeRepository()
    inspect, _, _ = use_case(repository, runner_result())
    created = await inspect(URL, OWNER, "inspect-1")
    get = GetInspection(repository, now=lambda: NOW)

    assert (await get(created.id, OWNER)).id == created.id
    with pytest.raises(ApplicationError) as foreign:
        await get(created.id, "b" * 64)
    assert foreign.value.code is ApplicationErrorCode.NOT_FOUND

    snapshot = repository.inspections[created.id]
    repository.inspections[created.id] = replace(snapshot, expires_at=NOW)
    expired = await get(created.id, OWNER)
    assert expired.id == created.id
    assert expired.expires_at == NOW
    assert expired.formats == ()


@pytest.mark.parametrize(
    "provider,url",
    [
        ("qqvideo", "https://v.qq.com/x/cover/mzc00200fr1ry1o/m00441h6knj.html"),
        ("youku", "https://v.youku.com/v_show/id_fixture.html"),
    ],
)
async def test_personal_routes_reach_runner_without_claiming_public_or_official_rights(
    provider, url
) -> None:
    context = replace(
        access_context(),
        provider_key=provider,
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
        credential_version_id="file-synthetic",
    )
    inspection = replace(
        runner_result(), access_context=context, extractor_key=provider
    )
    execute, _, _ = use_case(FakeRepository(), inspection)
    response = await execute(url, OWNER, "personal-inspection")
    assert response.formats
    assert response.access_decision.value == "downloadable"
    assert response.entitlement_state.value == "unknown"
    assert response.rights_basis is None
