from types import SimpleNamespace

import pytest
from app.services.provider_types import ProviderAccessMode
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
                context=download_request().access_context.to_domain(),
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
                access_mode=ProviderAccessMode.OPERATOR_MANAGED,
                strategy_id=None,
            ),
            cookie_jar=jar,
        )
        assert probes == ["https://video.twimg.com/test.mp4"]
        assert any(stream.audio_codec_family == "aac" for stream in result.streams)
    finally:
        workspace.cleanup()
