"""An explicitly advertised audio stream must not disappear as silent video."""

import json
from pathlib import Path

import pytest
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.process import ProcessResult
from app.workers.runner.service import MediaRunnerService
from helpers import result, settings, split_media_info


class AudioSupervisor:
    def __init__(self, info, *, probe_fails=False):
        self.info = info
        self.probe_fails = probe_fails
        self.probes = []

    async def run(self, argv, *, cwd, timeout_seconds, env=None):
        if "--dump-single-json" in argv:
            return result(json.dumps(self.info).encode())
        assert argv[0] == "ffprobe"
        self.probes.append((argv[-1], env))
        if self.probe_fails:
            return ProcessResult(1, b"", b"unavailable", False, False)
        return result(
            json.dumps(
                {
                    "streams": [{"codec_type": "audio", "codec_name": "aac"}],
                    "format": {"duration": "29.98"},
                }
            ).encode()
        )


@pytest.mark.parametrize("codec", [None, ""])
async def test_unknown_audio_codec_is_probed_before_accepting_video(tmp_path, codec):
    info = split_media_info()
    info["formats"][1].update(acodec=codec, url="https://cdn.example.com/audio.m3u8")
    supervisor = AudioSupervisor(info)
    response = await MediaRunnerService(
        settings(tmp_path), supervisor=supervisor
    ).inspect("https://vimeo.com/123456")

    assert response.options[0].plan.audio_codec_family.value == "aac"
    assert response.options[0].plan.hints.audio_id == "audio"
    assert response.media.duration_seconds == 30
    assert len(supervisor.probes) == 1
    url, environment = supervisor.probes[0]
    assert url == "https://cdn.example.com/audio.m3u8"
    assert environment["HTTPS_PROXY"] == "http://egress-proxy:3128"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("url", ["https://cdn.example.com/audio.m3u8", None])
async def test_unresolved_advertised_audio_does_not_become_silent_success(
    tmp_path: Path, url
):
    info = split_media_info()
    info["formats"][1].update(acodec=None, url=url)
    supervisor = AudioSupervisor(info, probe_fails=True)
    with pytest.raises(RunnerFailure) as caught:
        await MediaRunnerService(settings(tmp_path), supervisor=supervisor).inspect(
            "https://vimeo.com/123456"
        )
    assert caught.value.code == ("media_probe_failed" if url else "format_unavailable")
    assert list(tmp_path.iterdir()) == []


async def test_genuinely_silent_video_needs_no_audio_probe(tmp_path):
    info = split_media_info()
    info["formats"] = info["formats"][:1]
    supervisor = AudioSupervisor(info)
    response = await MediaRunnerService(
        settings(tmp_path), supervisor=supervisor
    ).inspect("https://vimeo.com/123456")
    assert response.options[0].plan.audio_codec_family.value == "none"
    assert supervisor.probes == []


async def test_complete_audio_metadata_needs_no_probe(tmp_path):
    supervisor = AudioSupervisor(split_media_info())
    response = await MediaRunnerService(
        settings(tmp_path), supervisor=supervisor
    ).inspect("https://vimeo.com/123456")
    assert response.options[0].plan.audio_codec_family.value == "aac"
    assert supervisor.probes == []
