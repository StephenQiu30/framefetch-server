from types import SimpleNamespace

import pytest
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.inspection_pipeline import RunnerInspectionPipeline
from app.workers.runner.options import build_download_options
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
        ("https://dai.ly/x93blhi", False),
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
                        "nb_frames": "1802" if nominal == "30/1" else "3602",
                        "duration_ts": 153687 if nominal == "30/1" else 153641,
                        "time_base": "1/2560",
                    },
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
            }
        ),
        download_probe_sample=AsyncMock(),
        probe=AsyncMock(
            return_value={
                "format": {"duration": "60.033008"},
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1920,
                        "height": 1080,
                        "avg_frame_rate": "60/1",
                        "r_frame_rate": "60/1",
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


async def test_dailymotion_clear_prefix_replaces_selected_track_rate(tmp_path):
    class Commands:
        async def inspect(self, *_args, **_kwargs):
            payload = split_media_info()
            payload.update(duration=217, fps=60, _framefetch_full_stream=True)
            payload["formats"] = [
                {
                    "format_id": "hls-380",
                    "url": "https://media.example.com/full.m3u8",
                    "_framefetch_probe_url": "https://media.example.com/first.ts",
                    "width": 512,
                    "height": 288,
                    "fps": None,
                    "vcodec": "h264",
                    "acodec": "aac",
                    "ext": "mp4",
                }
            ]
            return payload

        async def probe_remote_prefix(self, url, path, **kwargs):
            assert url.endswith("first.ts")
            return {
                "format": {"duration": "6"},
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 512,
                        "height": 288,
                        "avg_frame_rate": "30000/1001",
                    },
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
            }

    workspace = WorkspaceManager(tmp_path / "runner").create("dailymotion-prefix")
    try:
        inspection = await RunnerInspectionPipeline(
            settings(tmp_path), Commands()
        ).inspect(
            provider_request("https://dai.ly/x93blhi"),
            workspace,
            context=SimpleNamespace(
                provider_key="dailymotion", identity_used=False, resolved_layer="L1"
            ),
            cookie_jar=None,
        )
        assert inspection.duration_seconds == 217
        assert inspection.streams[0].fps == pytest.approx(30000 / 1001)
    finally:
        workspace.cleanup()


async def test_x_vfr_hls_cannot_outrank_verified_highest_mp4(tmp_path):
    from unittest.mock import AsyncMock

    from app.workers.runner.metadata import build_download_options

    payload = split_media_info()
    payload.update(extractor_key="Twitter", fps=240)
    payload["formats"] = [
        {
            "format_id": name,
            "ext": "mp4",
            "width": 3006,
            "height": 1604,
            "vcodec": "h264",
            "acodec": None,
            "fps": None,
            "protocol": "m3u8_native" if name.startswith("hls") else "https",
            "url": "https://video.twimg.com/" + name,
        }
        for name in ["hls-4108", "http-25128"]
    ]

    async def probe_remote(url, *args, **kwargs):
        hls = url.endswith("hls-4108")
        return {
            "format": {
                "format_name": "hls" if hls else "mov,mp4",
                "duration": "34.386667",
            },
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 3006,
                    "height": 1604,
                    "avg_frame_rate": "0/0" if hls else "137400/2579",
                    "r_frame_rate": "240/1",
                }
            ],
        }

    commands = SimpleNamespace(
        inspect=AsyncMock(return_value=payload),
        probe_remote=probe_remote,
        probe_hls_prefix=probe_remote,
    )
    workspace = WorkspaceManager(tmp_path / "runner").create("x-vfr")
    try:
        result = await RunnerInspectionPipeline(settings(tmp_path), commands).inspect(
            provider_request("https://x.com/creator/status/123"),
            workspace,
            context=SimpleNamespace(
                provider_key="x", identity_used=True, resolved_layer="L1"
            ),
            cookie_jar=tmp_path / "approved-cookie-jar",
        )
        plans = build_download_options(result.streams, max_options=10)
        assert len(plans) == 1
        assert plans[0].height == 1604
        assert plans[0].fps_bucket == "fps_60"
        assert plans[0].hints.video_id == "http-25128"
    finally:
        workspace.cleanup()


async def test_probe_cannot_replace_original_duration_with_a_short_candidate(tmp_path):
    from unittest.mock import AsyncMock

    payload = split_media_info()
    payload["formats"][0]["url"] = "https://cdn.example.org/video.mp4"
    payload["formats"][1]["url"] = "https://cdn.example.org/audio.m4a"

    async def probe(url, *_args, **_kwargs):
        streams = [{"codec_type": "audio", "codec_name": "aac"}]
        if url.endswith(".mp4"):
            streams.insert(
                0,
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30/1",
                },
            )
        return {"format": {"duration": "5"}, "streams": streams}

    commands = SimpleNamespace(
        inspect=AsyncMock(return_value=payload), probe_remote=probe
    )
    workspace = WorkspaceManager(tmp_path / "runner").create("original-duration")
    try:
        result = await RunnerInspectionPipeline(settings(tmp_path), commands).inspect(
            provider_request("https://www.bilibili.com/video/BV13x41117TL"),
            workspace,
            context=SimpleNamespace(
                provider_key="bilibili", identity_used=False, resolved_layer="L1"
            ),
            cookie_jar=None,
        )
        assert result.duration_seconds == 30
    finally:
        workspace.cleanup()


async def test_usable_lower_quality_does_not_hide_unknown_higher_quality(tmp_path):
    from unittest.mock import AsyncMock

    payload = split_media_info()
    video = payload["formats"][0]
    payload["formats"] = [
        {
            **video,
            "format_id": "small",
            "width": 1280,
            "height": 720,
            "url": "https://video.twimg.com/small.mp4",
        },
        {
            **video,
            "format_id": "large",
            "fps": None,
            "url": "https://video.twimg.com/large.mp4",
        },
    ]
    probe = AsyncMock(
        return_value={
            "format": {"format_name": "mov,mp4", "duration": "30"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "60000/1001",
                }
            ],
        }
    )
    commands = SimpleNamespace(
        inspect=AsyncMock(return_value=payload), probe_remote=probe
    )
    workspace = WorkspaceManager(tmp_path / "runner").create("higher-quality")
    try:
        result = await RunnerInspectionPipeline(settings(tmp_path), commands).inspect(
            provider_request("https://x.com/user/status/123"),
            workspace,
            context=SimpleNamespace(
                provider_key="x", identity_used=False, resolved_layer="L1"
            ),
            cookie_jar=None,
        )
        plans = build_download_options(result.streams, max_options=10)
        assert [plan.height for plan in plans] == [1080, 720]
        assert plans[0].fps_bucket == "fps_60"
        assert probe.await_count == 1
    finally:
        workspace.cleanup()


async def test_unusable_first_file_probe_continues_to_another_representation(tmp_path):
    from unittest.mock import AsyncMock

    payload = split_media_info()
    video = payload["formats"][0]
    payload["formats"] = [
        {**video, "format_id": "first", "fps": None, "acodec": "none"},
        {
            **video,
            "format_id": "second",
            "fps": None,
            "acodec": "none",
            "width": 1280,
            "height": 720,
        },
    ]
    commands = SimpleNamespace(
        inspect=AsyncMock(return_value=payload),
        download_probe_sample=AsyncMock(),
        probe=AsyncMock(
            side_effect=[
                {
                    "format": {"duration": "5"},
                    "streams": [{"codec_type": "audio", "codec_name": "aac"}],
                },
                {
                    "format": {"duration": "30"},
                    "streams": [
                        {
                            "codec_type": "video",
                            "codec_name": "h264",
                            "width": 1280,
                            "height": 720,
                            "avg_frame_rate": "30/1",
                        }
                    ],
                },
            ]
        ),
    )
    workspace = WorkspaceManager(tmp_path / "runner").create("sample-fallback")
    try:
        result = await RunnerInspectionPipeline(settings(tmp_path), commands).inspect(
            provider_request("https://x.com/user/status/123"),
            workspace,
            context=SimpleNamespace(
                provider_key="x", identity_used=False, resolved_layer="L1"
            ),
            cookie_jar=None,
        )
        assert result.duration_seconds == 30
        assert [
            plan.height
            for plan in build_download_options(result.streams, max_options=10)
        ] == [720]
        assert commands.download_probe_sample.await_count == 2
        assert [
            call.args[1] for call in commands.download_probe_sample.await_args_list
        ] == ["first", "second"]
        assert not list(workspace.path.glob("format-probe-*"))
    finally:
        workspace.cleanup()


async def test_probe_budget_prioritizes_quality_and_limits_concurrency(
    tmp_path,
):
    import asyncio
    from unittest.mock import AsyncMock

    config = settings(tmp_path)
    payload = split_media_info()
    video = payload["formats"][0]
    payload["formats"] = [
        {
            **video,
            "format_id": str(height),
            "fps": None,
            "acodec": "none",
            "width": height * 2,
            "height": height,
            "url": f"https://video.twimg.com/{height}.mp4",
            "filesize": config.runner_max_probe_sample_bytes + 1,
        }
        for height in range(80, 94)
    ]
    active = peak = 0
    seen = []

    async def probe(url, *_args, **_kwargs):
        nonlocal active, peak
        height = int(url.rsplit("/", 1)[-1].split(".")[0])
        seen.append(height)
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.001)
        active -= 1
        return {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": height * 2,
                    "height": height,
                    "avg_frame_rate": "30/1",
                }
            ],
            "format": {"duration": "5"},
        }

    commands = SimpleNamespace(
        inspect=AsyncMock(return_value=payload),
        probe_remote=probe,
        download_probe_sample=AsyncMock(),
    )
    workspace = WorkspaceManager(tmp_path / "runner").create("probe-budget")
    try:
        result = await RunnerInspectionPipeline(config, commands).inspect(
            provider_request("https://x.com/user/status/123"),
            workspace,
            context=SimpleNamespace(
                provider_key="x", identity_used=False, resolved_layer="L1"
            ),
            cookie_jar=None,
        )
        assert len(seen) == 12 and set(seen) == set(range(82, 94))
        assert peak == 4
        assert result.duration_seconds == 30
        commands.download_probe_sample.assert_not_awaited()
    finally:
        workspace.cleanup()


@pytest.mark.parametrize(
    "field,value",
    [
        pytest.param("width", [], id="non-numeric-width"),
        pytest.param("width", 10**400, id="overflow-width"),
        pytest.param("height", 10**400, id="overflow-height"),
        pytest.param("fps", 10**400, id="overflow-fps"),
    ],
)
async def test_malformed_candidate_numbers_do_not_crash_other_valid_quality(
    tmp_path,
    field,
    value,
):
    from unittest.mock import AsyncMock

    config = settings(tmp_path)
    payload = split_media_info()
    video = payload["formats"][0]
    payload["formats"] = [
        video,
        payload["formats"][1],
        {
            **video,
            "format_id": "malformed",
            "fps": None,
            field: value,
            "filesize": config.runner_max_probe_sample_bytes + 1,
        },
    ]
    commands = SimpleNamespace(inspect=AsyncMock(return_value=payload))
    workspace = WorkspaceManager(tmp_path / "runner").create("malformed-quality")
    try:
        result = await RunnerInspectionPipeline(config, commands).inspect(
            provider_request("https://x.com/user/status/123"),
            workspace,
            context=SimpleNamespace(
                provider_key="x", identity_used=False, resolved_layer="L1"
            ),
            cookie_jar=None,
        )
        assert [
            plan.height
            for plan in build_download_options(result.streams, max_options=10)
        ] == [1080]
    finally:
        workspace.cleanup()


async def test_x_probes_hls_even_with_known_same_quality_mp4_and_keeps_full_duration(
    tmp_path,
):
    from unittest.mock import AsyncMock

    payload = split_media_info()
    payload["duration"] = 15750
    muxed = {
        **payload["formats"][0],
        "format_id": "http",
        "acodec": "aac",
        "language": "zh-CN",
    }
    hls = {
        **payload["formats"][0],
        "format_id": "hls-video",
        "fps": None,
        "protocol": "m3u8_native",
        "url": "https://video.twimg.com/clear/1080.m3u8",
    }
    payload["formats"] = [muxed, hls]
    commands = SimpleNamespace(
        inspect=AsyncMock(return_value=payload),
        probe_hls_prefix=AsyncMock(
            return_value={
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1920,
                        "height": 1080,
                        "avg_frame_rate": "30/1",
                        "r_frame_rate": "30/1",
                    }
                ]
            }
        ),
        probe_remote=AsyncMock(side_effect=AssertionError("known MP4 needs no probe")),
        download_probe_sample=AsyncMock(
            side_effect=AssertionError(
                "HLS must not be fully downloaded during inspection"
            )
        ),
    )
    workspace = WorkspaceManager(tmp_path / "runner").create("long-hls")
    try:
        inspected = await RunnerInspectionPipeline(
            settings(tmp_path), commands
        ).inspect(
            provider_request("https://x.com/user/status/123"),
            workspace,
            context=SimpleNamespace(
                provider_key="x", identity_used=False, resolved_layer="L1"
            ),
            cookie_jar=None,
        )
        assert inspected.duration_seconds == 15750
        stream = next(s for s in inspected.streams if s.provider_id == "hls-video")
        assert stream.fps == 30
        assert stream.size_bytes is None
        assert inspected.download_info["formats"][1]["_framefetch_clear_hls"] is True
        commands.probe_hls_prefix.assert_awaited_once()
    finally:
        workspace.cleanup()
