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


async def test_bilibili_advertised_rate_is_probed_before_confirming_plan(tmp_path):
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
            provider_request("https://www.bilibili.com/video/BV13x41117TL"),
            workspace,
            context=SimpleNamespace(
                provider_key="bilibili", identity_used=False, resolved_layer="L1"
            ),
            cookie_jar=None,
        )
        assert len(probes) == 2
        assert all(
            plan.fps_bucket == "fps_30"
            for plan in build_download_options(inspection.streams, max_options=10)
        )
        assert inspection.streams[0].fps == pytest.approx(29.97, rel=0.001)
    finally:
        workspace.cleanup()
