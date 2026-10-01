from types import SimpleNamespace

import pytest
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.inspection_pipeline import RunnerInspectionPipeline
from app.workers.runner.provider_registry import provider_request
from app.workers.runner.workspace import WorkspaceManager
from helpers import download_request, settings, split_media_info


async def test_provider_probe_failure_is_not_downgraded_to_incomplete_metadata(
    tmp_path,
) -> None:
    class Commands:
        async def inspect(self, *_args, **_kwargs):
            payload = split_media_info()
            payload["duration"] = None
            formats = payload["formats"]
            assert isinstance(formats, list)
            formats[0]["url"] = "https://media.example.com/video"
            return payload

        async def probe_remote(self, *_args, **_kwargs):
            raise RunnerFailure("provider_rate_limited", status=429)

    workspace = WorkspaceManager(tmp_path / "runner").create("probe-failure")
    try:
        with pytest.raises(RunnerFailure) as caught:
            await RunnerInspectionPipeline(settings(tmp_path), Commands()).inspect(
                provider_request("https://media.example.com/video"),
                workspace,
                context=download_request().execution_context.to_domain(),
                cookie_jar=None,
            )
        assert caught.value.code == "provider_rate_limited"
        assert caught.value.status == 429
    finally:
        workspace.cleanup()


async def test_authenticated_x_resolves_missing_audio_without_forwarding_cookies(
    tmp_path,
) -> None:
    probes = []
    jar = tmp_path / "session.txt"

    class Commands:
        async def inspect(self, *_args, **kwargs):
            assert kwargs["cookie_jar"] == jar
            payload = split_media_info()
            payload["formats"] = [
                {
                    "format_id": "http-832",
                    "ext": "mp4",
                    "width": 640,
                    "height": 360,
                    "fps": 30,
                    "vcodec": None,
                    "acodec": None,
                    "url": "https://video.twimg.com/test.mp4",
                }
            ]
            return payload

        async def probe_remote(self, url, path, *, referer, failure_context):
            probes.append(url)
            return {
                "format": {"duration": "45.25"},
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 640,
                        "height": 360,
                        "r_frame_rate": "30/1",
                    },
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
            }

    workspace = WorkspaceManager(tmp_path / "runner").create("x-sparse")
    try:
        result = await RunnerInspectionPipeline(settings(tmp_path), Commands()).inspect(
            provider_request("https://x.com/user/status/123"),
            workspace,
            context=SimpleNamespace(
                provider_key="x",
                identity_used=True,
                resolved_layer="L1",
            ),
            cookie_jar=jar,
        )
        assert probes == ["https://video.twimg.com/test.mp4"]
        assert any(stream.audio_codec_family == "aac" for stream in result.streams)
    finally:
        workspace.cleanup()


async def test_youku_required_identity_probes_clear_prefix_and_keeps_full_duration(
    tmp_path,
):
    probes = []
    jar = tmp_path / "approved-cookie-jar"

    class Commands:
        async def inspect(self, *_args, **kwargs):
            assert kwargs["cookie_jar"] == jar
            payload = split_media_info()
            payload.update(
                id="XOTUxMzg4NDMy", duration=702.08, _framefetch_full_stream=True
            )
            payload["formats"] = [
                {
                    "format_id": "full",
                    "url": "https://media.example.com/full.m3u8",
                    "_framefetch_probe_url": "https://media.example.com/part.ts",
                    "protocol": "m3u8_native",
                    "ext": "mp4",
                    "width": 640,
                    "height": 360,
                    "vcodec": None,
                    "acodec": None,
                }
            ]
            return payload

        async def probe_remote_prefix(self, url, path, *, referer, failure_context):
            probes.append(url)
            return {
                "format": {"duration": "10"},
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 640,
                        "height": 360,
                        "avg_frame_rate": "0/0",
                        "r_frame_rate": "25/1",
                    },
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
            }

    workspace = WorkspaceManager(tmp_path / "runner").create("youku-full-prefix")
    try:
        result = await RunnerInspectionPipeline(settings(tmp_path), Commands()).inspect(
            provider_request("https://v.youku.com/v_show/id_XOTUxMzg4NDMy.html"),
            workspace,
            context=SimpleNamespace(
                provider_key="youku", identity_used=True, resolved_layer="L1"
            ),
            cookie_jar=jar,
        )
        assert probes == ["https://media.example.com/part.ts"]
        assert result.duration_seconds == 702.08
        assert result.streams[0].video_codec_family == "h264"
        assert result.streams[0].audio_codec_family == "aac"
    finally:
        workspace.cleanup()


@pytest.mark.parametrize(
    "url,authenticated",
    [
        ("https://www.bilibili.com/video/BV13x41117TL", False),
        ("https://www.bilibili.com/video/BV13x41117TL", True),
        ("https://clips.twitch.tv/Test", False),
    ],
)
async def test_advertised_rate_is_probed_before_confirming_plan(
    tmp_path, authenticated, url
):
    from app.workers.runner.metadata import build_download_options

    probes = []

    class Commands:
        async def inspect(self, *_args, **_kwargs):
            payload = split_media_info()
            payload["formats"][0].update(
                fps=30.303, url="https://media.example.com/video.mp4"
            )
            payload["formats"][1]["url"] = "https://media.example.com/audio.m4a"
            return payload

        async def probe_remote(self, url, path, *, referer, failure_context):
            probes.append(url)
            stream = (
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30000/1001",
                }
                if url.endswith(".mp4")
                else {"codec_type": "audio", "codec_name": "aac"}
            )
            return {"format": {"duration": "30"}, "streams": [stream]}

    workspace = WorkspaceManager(tmp_path / "runner").create("bilibili-fps")
    try:
        inspection = await RunnerInspectionPipeline(
            settings(tmp_path), Commands()
        ).inspect(
            provider_request(url),
            workspace,
            context=SimpleNamespace(
                provider_key=provider_request(url).profile.key,
                identity_used=authenticated,
                resolved_layer="L1",
            ),
            cookie_jar=tmp_path / "identity.txt" if authenticated else None,
        )
        assert len(probes) == 2
        assert all(
            plan.fps_bucket == "fps_30"
            for plan in build_download_options(inspection.streams, max_options=10)
        )
        assert inspection.streams[0].fps == pytest.approx(29.97, rel=0.001)
    finally:
        workspace.cleanup()


@pytest.mark.parametrize("split,silent", [(False, False), (True, False), (False, True)])
async def test_instagram_tracks_are_probed_before_audio_plan(tmp_path, split, silent):
    from unittest.mock import AsyncMock

    from app.workers.runner.metadata import build_download_options

    payload = split_media_info()
    video = payload["formats"][0]
    video.update(acodec=None, url="https://cdn.example.org/video.mp4")
    payload["formats"] = [video]
    if split:
        payload["formats"].append(
            {
                "format_id": "audio",
                "url": "https://cdn.example.org/audio.m4a",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "aac",
            }
        )
    video_probe = {
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "avg_frame_rate": "30000/1001",
    }
    audio_probe = {"codec_type": "audio", "codec_name": "aac"}

    async def probe(url, *_args, **_kwargs):
        streams = [audio_probe] if url.endswith(".m4a") else [video_probe]
        if not split and not silent:
            streams.append(audio_probe)
        return {"format": {"duration": "45.25"}, "streams": streams}

    commands = SimpleNamespace(
        inspect=AsyncMock(return_value=payload),
        probe_remote=AsyncMock(side_effect=probe),
    )
    workspace = WorkspaceManager(tmp_path / "runner").create("instagram-audio")
    try:
        result = await RunnerInspectionPipeline(settings(tmp_path), commands).inspect(
            provider_request("https://www.instagram.com/reel/Chunk8-jurw/"),
            workspace,
            context=SimpleNamespace(
                provider_key="instagram", identity_used=True, resolved_layer="L1"
            ),
            cookie_jar=tmp_path / "identity.txt",
        )
        plans = build_download_options(result.streams, max_options=10)
        assert plans
        assert {plan.audio_codec_family for plan in plans} == {
            "none" if silent else "aac"
        }
        assert all(plan.fps_bucket == "fps_30" for plan in plans)
        assert commands.probe_remote.await_count == (2 if split else 1)
    finally:
        workspace.cleanup()


async def test_twitch_declared_sixty_fps_is_replaced_by_actual_thirty(tmp_path):
    from unittest.mock import AsyncMock

    from app.workers.runner.metadata import build_download_options

    payload = split_media_info()
    payload["formats"] = [
        {
            **payload["formats"][0],
            "fps": 60,
            "acodec": "aac",
            "url": "https://cdn.example.org/clip.mp4",
        }
    ]
    commands = SimpleNamespace(
        inspect=AsyncMock(return_value=payload),
        probe_remote=AsyncMock(
            return_value={
                "format": {"duration": "45.25"},
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1920,
                        "height": 1080,
                        "avg_frame_rate": "30000/1001",
                    },
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
            }
        ),
    )
    workspace = WorkspaceManager(tmp_path / "runner").create("twitch-fps")
    try:
        result = await RunnerInspectionPipeline(settings(tmp_path), commands).inspect(
            provider_request("https://clips.twitch.tv/FaintLightGullWholeWheat"),
            workspace,
            context=SimpleNamespace(
                provider_key="twitch", identity_used=False, resolved_layer="L1"
            ),
            cookie_jar=None,
        )
        assert all(
            plan.fps_bucket == "fps_30"
            for plan in build_download_options(result.streams, max_options=10)
        )
    finally:
        workspace.cleanup()


@pytest.mark.parametrize(
    "average,nominal,bucket",
    [
        ("4613120/153687", "30/1", "fps_30"),
        ("9221120/153641", "60/1", "fps_60"),
        ("30/1", "60/1", "fps_30"),
    ],
)
async def test_twitch_remote_clip_edit_list_does_not_change_rate_bucket(
    tmp_path, average, nominal, bucket
):
    from unittest.mock import AsyncMock

    from app.workers.runner.metadata import build_download_options

    payload = split_media_info()
    payload["formats"] = [
        {
            **payload["formats"][0],
            "fps": 0,
            "acodec": "aac",
            "url": "https://cdn.example.org/clip.mp4",
        }
    ]
    commands = SimpleNamespace(
        inspect=AsyncMock(return_value=payload),
        probe_remote=AsyncMock(
            return_value={
                "format": {"duration": "60.033008"},
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1920,
                        "height": 1080,
                        "avg_frame_rate": average,
                        "r_frame_rate": nominal,
                    },
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
            }
        ),
    )
    workspace = WorkspaceManager(tmp_path / "runner").create("twitch-clip-fps")
    try:
        inspection = await RunnerInspectionPipeline(
            settings(tmp_path), commands
        ).inspect(
            provider_request("https://clips.twitch.tv/FaintLightGullWholeWheat"),
            workspace,
            context=SimpleNamespace(
                provider_key="twitch", identity_used=False, resolved_layer="L1"
            ),
            cookie_jar=None,
        )
        assert all(
            plan.fps_bucket == bucket
            for plan in build_download_options(inspection.streams, max_options=10)
        )
    finally:
        workspace.cleanup()
