from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.process import ProcessResult
from app.workers.runner.provider_registry import provider_request
from app.workers.runner.service import MediaRunnerService
from helpers import download_request, result, settings, split_media_info
from yt_dlp import YoutubeDL
from yt_dlp.extractor import get_info_extractor


@pytest.mark.parametrize(
    "webpage_url,extractor_key",
    (
        ("https://www.dailymotion.com/video/x", "Dailymotion"),
        ("https://media.example.com/video", "Dailymotion"),
        ("https://www.douyin.com/video/1", "Douyin"),
        ("https://media.example.com/video", "DouyinSharePage"),
    ),
)
async def test_generic_cannot_bypass_provider_route_after_extraction(
    tmp_path, webpage_url, extractor_key
):
    payload = {
        **split_media_info(),
        "webpage_url": webpage_url,
        "extractor_key": extractor_key,
    }
    supervisor = FixtureSupervisor(payload)
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as error:
        await service.inspect("https://media.example.com/video")

    assert error.value.code == "provider_unsupported"
    assert len(supervisor.calls) == 1


async def test_generic_named_upstream_extractor_can_inspect_its_own_url(tmp_path):
    url = "https://commons.wikimedia.org/wiki/File:Big_buck_bunny_mcu.ogv"
    supervisor = FixtureSupervisor(
        {**split_media_info(), "webpage_url": url, "extractor_key": "Wikimedia"}
    )
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    inspected = await service.inspect(url)

    assert inspected.media.extractor_key == "Wikimedia"
    assert len(supervisor.calls) == 1


@pytest.mark.parametrize("extractor_key", ("Generic", None, "PeerTube"))
async def test_generic_requires_a_named_extractor_with_final_page(
    tmp_path, extractor_key
):
    supervisor = FixtureSupervisor(
        {**split_media_info(), "extractor_key": extractor_key}
    )
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as error:
        await service.inspect("https://media.example.com/video")

    assert error.value.code == "provider_unsupported"
    assert len(supervisor.calls) == 1


async def test_generic_requires_the_final_page_identity(tmp_path):
    payload = split_media_info()
    payload.pop("webpage_url")
    supervisor = FixtureSupervisor(payload)
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as error:
        await service.inspect("https://media.example.com/video")

    assert error.value.code == "provider_unsupported"
    assert len(supervisor.calls) == 1


async def test_unapproved_peertube_instance_does_not_use_generic(tmp_path):
    url = "https://video.unapproved.example/w/AbCdEfGhIjKlMnOpQrStUv"
    supervisor = FixtureSupervisor(
        {**split_media_info(), "webpage_url": url, "extractor_key": "PeerTube"}
    )
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as error:
        await service.inspect(url)

    assert error.value.code == "provider_unsupported"
    assert len(supervisor.calls) == 1


async def test_generic_download_reinspection_rejects_cross_provider_result(tmp_path):
    supervisor = FixtureSupervisor(
        {
            **split_media_info(),
            "webpage_url": "https://www.dailymotion.com/video/x",
            "extractor_key": "Dailymotion",
        }
    )
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as error:
        await service.download(download_request())

    assert error.value.code == "provider_unsupported"
    assert len(supervisor.calls) == 1


async def test_generic_collection_cannot_hide_a_cross_provider_member(tmp_path):
    url = "https://commons.wikimedia.org/wiki/File:Big_buck_bunny_mcu.ogv"
    supervisor = FixtureSupervisor(
        {
            **split_media_info(),
            "webpage_url": url,
            "extractor_key": "Wikimedia",
            "_type": "playlist",
            "entries": [
                {
                    **split_media_info(),
                    "webpage_url": "https://www.dailymotion.com/video/x",
                    "extractor_key": "Dailymotion",
                }
            ],
        }
    )
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as error:
        await service.inspect(url)

    assert error.value.code == "provider_unsupported"
    assert len(supervisor.calls) == 1


async def test_generic_clip_cannot_mask_youtube_in_transparent_merge(tmp_path):
    url = "https://ladigitale.dev/digiview/#/v/67a8ea5644d7a"
    youtube_url = "https://www.youtube.com/watch?v=abc123"
    assert get_info_extractor("Digiview").suitable(url)
    inner = {
        **split_media_info(),
        "extractor_key": "Youtube",
        "extractor": "youtube",
        "webpage_url": youtube_url,
    }
    outer = {
        "_type": "url_transparent",
        "url": youtube_url,
        "ie_key": "Youtube",
        "id": "clip123",
        "title": "Outer",
        "section_start": 5,
        "section_end": 15,
        "extractor_key": "Digiview",
        "extractor": "digiview",
        "webpage_url": url,
        "original_url": url,
    }
    ydl = YoutubeDL(
        {"skip_download": True, "quiet": True, "ignore_no_formats_error": True}
    )
    ydl.extract_info = lambda *args, **kwargs: inner.copy()
    merged = ydl.process_ie_result(outer, download=False)
    assert merged.get("_type") is None
    assert merged["extractor_key"] == "Digiview"
    assert merged["webpage_url"] == url
    supervisor = FixtureSupervisor(merged)
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as error:
        await service.inspect(url)

    assert error.value.code == "provider_unsupported"
    assert len(supervisor.calls) == 1


class ThumbnailStream:
    status_code = 200
    headers = {"content-type": "image/avif", "content-length": "5"}
    is_redirect = False

    def raise_for_status(self) -> None:
        return None

    async def __aenter__(self) -> ThumbnailStream:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def aiter_bytes(self):
        yield b"cover"


class ThumbnailClient:
    def __init__(self, **kwargs: object) -> None:
        self.options = kwargs
        self.requests: list[tuple[str, str]] = []

    async def __aenter__(self) -> ThumbnailClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def stream(self, method: str, url: str, **_: object) -> ThumbnailStream:
        self.requests.append((method, url))
        return ThumbnailStream()


class ScriptedThumbnailStream:
    def __init__(
        self,
        status_code: int,
        *,
        content: bytes = b"cover",
        content_type: str = "image/jpeg",
    ) -> None:
        self.status_code = status_code
        self.headers = {
            "content-type": content_type,
            "content-length": str(len(content)),
        }
        self.is_redirect = False
        self._content = content

    async def __aenter__(self) -> ScriptedThumbnailStream:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def aiter_bytes(self):
        yield self._content


class ScriptedThumbnailClient(ThumbnailClient):
    def __init__(
        self,
        responses: list[ScriptedThumbnailStream],
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._responses = responses

    def stream(self, method: str, url: str, **_: object) -> ScriptedThumbnailStream:
        self.requests.append((method, url))
        return self._responses.pop(0)


class FixtureSupervisor:
    def __init__(self, info: dict[str, object]) -> None:
        self.info = info
        self.calls: list[tuple[tuple[str, ...], Mapping[str, str] | None]] = []

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        command = tuple(argv)
        self.calls.append((command, env))
        if "--dump-single-json" in command:
            return result(json.dumps(self.info).encode())
        if command[0] == "yt-dlp":
            output = Path(command[command.index("--output") + 1])
            output.write_bytes(b"downloaded-stream")
            return result()
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"final-media")
            return result()
        if command[0] == "ffprobe":
            probe = {
                "format": {"format_name": "mov,mp4,m4a", "duration": "30"},
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1920,
                        "height": 1080,
                        "avg_frame_rate": "30/1",
                    },
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
            }
            return result(json.dumps(probe).encode())
        raise AssertionError(command)


class ProgressSupervisor(FixtureSupervisor):
    def __init__(self, info: dict[str, object]) -> None:
        super().__init__(info)
        self.partial_written = asyncio.Event()

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        command = tuple(argv)
        if (
            command[0] == "yt-dlp"
            and "--dump-single-json" not in command
            and command[command.index("--format") + 1] == "video"
        ):
            output = Path(command[command.index("--output") + 1])
            partial = output.with_name(f"{output.name}.part")
            partial.write_bytes(b"x" * 50)
            self.partial_written.set()
            await asyncio.sleep(0.08)
            partial.unlink()
        return await super().run(
            argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
        )


class ProbeSampleSupervisor(FixtureSupervisor):
    def __init__(self, info: dict[str, object]) -> None:
        super().__init__(info)
        self.inspection_attempts = 0

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        command = tuple(argv)
        if "--dump-single-json" in command:
            self.inspection_attempts += 1
        if command[0] == "ffprobe" and str(command[-1]).startswith("https://"):
            self.calls.append((command, env))
            return ProcessResult(1, b"", b"forbidden", False, False)
        return await super().run(
            argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
        )


class RemoteProbeFailureSupervisor(FixtureSupervisor):
    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        command = tuple(argv)
        if command[0] == "ffprobe" and str(command[-1]).startswith("https://"):
            self.calls.append((command, env))
            return ProcessResult(1, b"", b"forbidden", False, False)
        return await super().run(
            argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
        )


class DirtyWorkspaceProbeSupervisor(RemoteProbeFailureSupervisor):
    def __init__(self, info: dict[str, object]) -> None:
        super().__init__(info)
        self.inspection_cwd: Path | None = None
        self.sample_cwd: Path | None = None

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        command = tuple(argv)
        if "--dump-single-json" in command:
            self.inspection_cwd = cwd
            cache = cwd / ".cache" / "yt-dlp"
            cache.mkdir(parents=True)
            (cache / "existing").write_bytes(b"x" * (9 * 1024**2))
        elif command[0] == "yt-dlp" and "--max-filesize" in command:
            self.sample_cwd = cwd
            await asyncio.sleep(0.05)
        return await super().run(
            argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
        )


class ClassifiedFailureThenSuccessSupervisor(FixtureSupervisor):
    def __init__(self, info: dict[str, object], stderr: bytes) -> None:
        super().__init__(info)
        self.stderr = stderr
        self.inspection_attempts = 0

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        command = tuple(argv)
        if "--dump-single-json" in command:
            self.inspection_attempts += 1
            if self.inspection_attempts == 1:
                self.calls.append((command, env))
                return ProcessResult(
                    1,
                    b"",
                    self.stderr,
                    False,
                    False,
                )
        return await super().run(
            argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
        )


class TransientFailureSupervisor(FixtureSupervisor):
    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        del cwd, timeout_seconds
        self.calls.append((tuple(argv), env))
        return ProcessResult(1, b"", b"transient", False, False)


async def test_download_reinspects_selects_semantics_and_verifies_artifact(
    tmp_path: Path,
) -> None:
    supervisor = FixtureSupervisor(split_media_info())
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    response = await service.download(download_request())

    artifact = Path(response.workspace_path) / response.artifact.relative_path
    assert artifact.read_bytes() == b"final-media"
    assert response.artifact.sha256 == hashlib.sha256(b"final-media").hexdigest()
    commands = [call[0] for call in supervisor.calls]
    ytdlp = [command for command in commands if command[0] == "yt-dlp"]
    assert all("http://egress-proxy:3128" in command for command in ytdlp)
    assert all("--plugin-dirs" in command for command in ytdlp)
    assert all("--cookies" not in command for command in ytdlp)
    downloads = [command for command in ytdlp if "--format" in command]
    assert all("--load-info-json" in command for command in downloads)
    assert all(
        "https://media.example.com/video" not in command for command in downloads
    )
    info_path = Path(downloads[0][downloads[0].index("--load-info-json") + 1])
    assert info_path.stat().st_mode & 0o777 == 0o600
    assert json.loads(info_path.read_text())["id"] == "controlled"
    assert all(
        command[command.index("--js-runtimes") + 1] == "node" for command in ytdlp
    )
    plugin_root = Path(ytdlp[0][ytdlp[0].index("--plugin-dirs") + 1])
    assert (plugin_root / "plugins/yt_dlp_plugins/extractor/mediatrack.py").is_file()
    assert [command[command.index("--format") + 1] for command in ytdlp[1:]] == [
        "video",
        "audio",
    ]
    ffmpeg = next(command for command in commands if command[0] == "ffmpeg")
    assert "copy" in ffmpeg
    assert ffmpeg[ffmpeg.index("-protocol_whitelist") + 1] == "file,crypto,data"
    ffprobe = next(command for command in commands if command[0] == "ffprobe")
    assert ffprobe[ffprobe.index("-protocol_whitelist") + 1] == "file,crypto,data"
    assert all("RUNNER_HMAC_SECRET" not in (env or {}) for _, env in supervisor.calls)
    status = await service.status("job_123")
    assert status.stage.value == "ready"
    assert status.progress == 100


async def test_download_reports_byte_progress_while_stream_is_running(
    tmp_path: Path,
) -> None:
    info = split_media_info()
    formats = info["formats"]
    assert isinstance(formats, list)
    formats[0]["filesize"] = 100
    formats[1]["filesize"] = 100
    supervisor = ProgressSupervisor(info)
    configured = settings(tmp_path).model_copy(
        update={"runner_workspace_poll_interval_seconds": 0.01}
    )
    service = MediaRunnerService(configured, supervisor=supervisor)

    operation = asyncio.create_task(service.download(download_request()))
    await asyncio.wait_for(supervisor.partial_written.wait(), timeout=1)
    await asyncio.sleep(0.03)

    status = await service.status("job_123")
    assert status.stage.value == "downloading"
    assert 10 < status.progress < 40

    await operation


async def test_download_reselects_current_streams_instead_of_stale_hints(
    tmp_path: Path,
) -> None:
    info = split_media_info()
    info["formats"] = [
        {
            "format_id": "video-low",
            "ext": "mp4",
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "tbr": 900,
            "vcodec": "avc1.640028",
            "acodec": "none",
        },
        {
            "format_id": "video-high",
            "ext": "mp4",
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "tbr": 1800,
            "vcodec": "avc1.640028",
            "acodec": "none",
        },
        {
            "format_id": "audio-low",
            "ext": "m4a",
            "abr": 32,
            "vcodec": "none",
            "acodec": "mp4a.40.2",
            "language": "zh-CN",
        },
        {
            "format_id": "audio-high",
            "ext": "m4a",
            "abr": 130,
            "vcodec": "none",
            "acodec": "mp4a.40.2",
            "language": "zh-CN",
        },
    ]
    supervisor = FixtureSupervisor(info)
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    await service.download(download_request())

    ytdlp = [
        command
        for command, _ in supervisor.calls
        if command[0] == "yt-dlp" and "--format" in command
    ]
    assert [command[command.index("--format") + 1] for command in ytdlp] == [
        "video-high",
        "audio-high",
    ]


async def test_download_never_downgrades_and_cleans_failed_workspace(
    tmp_path: Path,
) -> None:
    supervisor = FixtureSupervisor(split_media_info(height=720))
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as caught:
        await service.download(download_request())

    assert caught.value.code == "context_changed"
    assert list(tmp_path.iterdir()) == []


async def test_download_rejects_source_identity_drift_before_download(
    tmp_path: Path,
) -> None:
    changed = split_media_info()
    changed["id"] = "different-media"
    supervisor = FixtureSupervisor(changed)
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as caught:
        await service.download(download_request())

    assert caught.value.code == "source_changed"
    assert len(supervisor.calls) == 1
    assert list(tmp_path.iterdir()) == []


async def test_inspect_requires_at_least_one_semantic_option(tmp_path: Path) -> None:
    info = split_media_info()
    info["formats"] = [
        {
            "format_id": "unsupported",
            "ext": "mp4",
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "vcodec": "unknown",
            "acodec": "none",
            "filesize": 9 * 1024**2,
        }
    ]
    supervisor = FixtureSupervisor(info)
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as caught:
        await service.inspect("https://media.example.com/video")

    assert caught.value.code == "format_unavailable"


@pytest.mark.usefixtures("http_only_ladder")
async def test_inspect_does_not_retry_unclassified_provider_text(
    tmp_path: Path,
) -> None:
    configured = settings(tmp_path).model_copy(
        update={"runner_inspect_timeout_seconds": 0.05}
    )
    supervisor = TransientFailureSupervisor(split_media_info())
    service = MediaRunnerService(configured, supervisor=supervisor)

    with pytest.raises(RunnerFailure) as caught:
        await service.inspect("https://www.douyin.com/video/7662711608636889201")

    assert caught.value.code == "inspection_failed"
    assert caught.value.failure.failure_class.value == "extractor_broken"
    assert len(supervisor.calls) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.usefixtures("http_only_ladder")
async def test_inspect_enriches_sparse_provider_formats_with_bounded_probe(
    tmp_path: Path,
) -> None:
    info = split_media_info()
    info["formats"] = [
        {
            "format_id": "http-832",
            "ext": "mp4",
            "url": "https://cdn.example.com/video.mp4",
        }
    ]
    supervisor = FixtureSupervisor(info)
    source_url = "https://www.douyin.com/video/7662711608636889201"
    configured = settings(tmp_path).model_copy(
        update={"runner_egress_proxy": "http://douyin-egress-proxy:3128"}
    )
    service = MediaRunnerService(configured, supervisor=supervisor)

    response = await service.inspect(source_url)

    assert response.streams[0].height == 1080
    ffprobe, probe_environment = next(
        (command, environment)
        for command, environment in supervisor.calls
        if command[0] == "ffprobe" and str(command[-1]).startswith("https://")
    )
    assert ffprobe[-1] == "https://cdn.example.com/video.mp4"
    assert (
        ffprobe[ffprobe.index("-protocol_whitelist") + 1]
        == "http,https,tcp,tls,crypto,httpproxy"
    )
    assert ffprobe[ffprobe.index("-referer") + 1] == source_url
    assert "Mozilla/5.0" in ffprobe[ffprobe.index("-user_agent") + 1]
    assert probe_environment is not None
    assert probe_environment["HTTPS_PROXY"] == "http://douyin-egress-proxy:3128"


async def test_inspect_accepts_ytdlp_top_level_selected_direct_format(
    tmp_path: Path,
) -> None:
    info = split_media_info()
    info.pop("formats")
    info.update(
        {
            "format_id": "direct-0",
            "ext": "mp4",
            "url": "https://cdn.example.com/spotlight.mp4",
            "vcodec": None,
            "acodec": None,
        }
    )
    supervisor = FixtureSupervisor(info)
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    response = await service.inspect("https://media.example.com/video")

    assert response.streams[0].provider_id == "direct-0"
    assert response.streams[0].video_codec_family.value == "h264"
    assert response.streams[0].audio_codec_family.value == "aac"


async def test_inspect_recovers_missing_duration_from_sparse_probe(
    tmp_path: Path,
) -> None:
    info = split_media_info()
    info["duration"] = None
    info["formats"] = [
        {
            "format_id": "http-832",
            "ext": "mp4",
            "url": "https://cdn.example.com/video.mp4",
        }
    ]
    supervisor = FixtureSupervisor(info)
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    response = await service.inspect("https://media.example.com/video")

    assert response.media.duration_seconds == 30
    assert response.streams[0].video_codec_family.value == "h264"


async def test_inspect_prefers_downloadable_stream_duration_from_probe(
    tmp_path: Path,
) -> None:
    info = split_media_info()
    info["duration"] = 24
    info["formats"] = [
        {
            "format_id": "http-832",
            "ext": "mp4",
            "url": "https://cdn.example.com/video.mp4",
        }
    ]
    supervisor = FixtureSupervisor(info)
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    response = await service.inspect("https://media.example.com/video")

    assert response.media.duration_seconds == 30


def douyin_muxed_info() -> dict[str, object]:
    info = split_media_info()
    info["duration"] = 24
    info["formats"] = [
        {
            "format_id": "download_addr-0",
            "ext": "mp4",
            "url": "https://v3-dy.example.com/video.mp4",
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "vcodec": "h264",
            "acodec": "aac",
        }
    ]
    return info


@pytest.mark.usefixtures("http_only_ladder")
async def test_douyin_inspect_uses_media_duration_instead_of_page_metadata(
    tmp_path: Path,
) -> None:
    supervisor = FixtureSupervisor(douyin_muxed_info())
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    response = await service.inspect("https://www.douyin.com/video/7662711608636889201")

    assert response.media.duration_seconds == 30
    remote_probes = [
        command
        for command, _ in supervisor.calls
        if command[0] == "ffprobe" and str(command[-1]).startswith("https://")
    ]
    assert len(remote_probes) == 1


@pytest.mark.usefixtures("http_only_ladder")
async def test_douyin_inspect_fails_closed_without_media_duration(
    tmp_path: Path,
) -> None:
    supervisor = RemoteProbeFailureSupervisor(douyin_muxed_info())
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as caught:
        await service.inspect("https://www.douyin.com/video/7662711608636889201")

    assert caught.value.code == "media_probe_failed"
    assert list(tmp_path.iterdir()) == []


async def test_single_inspection_uses_bounded_local_probe_sample(
    tmp_path: Path,
) -> None:
    info = split_media_info()
    info["formats"] = [
        {
            "format_id": "h264-540p",
            "ext": "mp4",
            "width": 576,
            "height": 1024,
            "vcodec": "h264",
            "acodec": "aac",
            "filesize": 1_300_000,
            "duration": 12,
            "url": "https://cdn.example.com/video.mp4",
        }
    ]
    supervisor = ProbeSampleSupervisor(info)
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    response = await service.inspect("https://media.example.com/video")

    assert supervisor.inspection_attempts == 1
    assert response.media.duration_seconds == 30
    assert response.streams[0].fps == 30
    sample = next(
        command
        for command, _ in supervisor.calls
        if command[0] == "yt-dlp" and "--max-filesize" in command
    )
    assert sample[sample.index("--max-filesize") + 1] == str(8 * 1024**2)
    assert not (tmp_path / "format-probe.input").exists()


async def test_inspect_boundedly_probes_a_format_with_unknown_filesize(
    tmp_path: Path,
) -> None:
    info = split_media_info()
    info["duration"] = None
    info["formats"] = [
        {
            "format_id": "sparse-mp4",
            "ext": "mp4",
            "url": "https://cdn.example.com/sparse.mp4",
        }
    ]
    supervisor = RemoteProbeFailureSupervisor(info)
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    response = await service.inspect("https://media.example.com/video")

    assert response.media.duration_seconds == 30
    assert response.streams[0].video_codec_family.value == "h264"
    sample = next(
        command
        for command, _ in supervisor.calls
        if command[0] == "yt-dlp" and "--max-filesize" in command
    )
    assert sample[sample.index("--max-filesize") + 1] == str(8 * 1024**2)
    assert "--no-cache-dir" in sample
    assert not (tmp_path / "format-probe.input").exists()


async def test_probe_sample_uses_a_clean_isolated_workspace(tmp_path: Path) -> None:
    info = split_media_info()
    info["duration"] = 10
    info["formats"] = [
        {
            "format_id": "sparse-mp4",
            "ext": "mp4",
            "url": "https://cdn.example.com/sparse.mp4",
        }
    ]
    supervisor = DirtyWorkspaceProbeSupervisor(info)
    configured = settings(tmp_path).model_copy(
        update={"runner_workspace_poll_interval_seconds": 0.005}
    )
    service = MediaRunnerService(configured, supervisor=supervisor)

    response = await service.inspect("https://media.example.com/video")

    assert response.streams[0].video_codec_family.value == "h264"
    assert supervisor.inspection_cwd is not None
    assert supervisor.sample_cwd is not None
    assert supervisor.sample_cwd != supervisor.inspection_cwd
    assert supervisor.sample_cwd.parent == supervisor.inspection_cwd
    assert not supervisor.sample_cwd.exists()


async def test_inspect_does_not_immediately_retry_tumblr_rate_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor = ClassifiedFailureThenSuccessSupervisor(
        split_media_info(),
        b"ERROR: HTTP Error 429: Too Many Requests",
    )
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(
        "app.workers.runner.inspection_pipeline.asyncio.sleep", record_sleep
    )
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as caught:
        await service.inspect(
            "https://www.tumblr.com/maskofthedragon/"
            "626907179849564160/mona-talking-in-english"
        )

    assert caught.value.code == "rate_limited"
    assert supervisor.inspection_attempts == 1
    assert delays == []


@pytest.mark.usefixtures("http_only_ladder")
async def test_inspect_does_not_retry_xiaohongshu_egress_challenge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor = ClassifiedFailureThenSuccessSupervisor(
        split_media_info(),
        b"ERROR: Xiaohongshu request verification required",
    )
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(
        "app.workers.runner.inspection_pipeline.asyncio.sleep", record_sleep
    )
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as caught:
        await service.inspect(
            "https://www.xiaohongshu.com/explore/64a6b35f000000001f01465c",
        )

    assert caught.value.code == "challenge"
    assert supervisor.inspection_attempts == 1
    assert delays == []


async def test_inspect_retries_tiktok_transient_in_same_layer_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor = ClassifiedFailureThenSuccessSupervisor(
        split_media_info(),
        b"ERROR: TikTok official player API temporarily unavailable",
    )
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(
        "app.workers.runner.inspection_pipeline.asyncio.sleep", record_sleep
    )
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    response = await service.inspect(
        "https://www.tiktok.com/@creator/video/6742501081818877190",
    )
    assert response.media.title
    assert supervisor.inspection_attempts == 2
    assert delays == [0.0]


async def test_inspect_does_not_retry_tiktok_rate_limited_temporary_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor = ClassifiedFailureThenSuccessSupervisor(
        split_media_info(),
        b"WARNING: HTTP Error 429: Too Many Requests\n"
        b"ERROR: TikTok official player API temporarily unavailable",
    )
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(
        "app.workers.runner.inspection_pipeline.asyncio.sleep", record_sleep
    )
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as caught:
        await service.inspect(
            "https://www.tiktok.com/@creator/video/6742501081818877190",
        )

    assert caught.value.code == "rate_limited"
    assert supervisor.inspection_attempts == 1
    assert delays == []


@pytest.mark.usefixtures("http_only_ladder")
async def test_youtube_unclassified_failure_uses_one_attempt(
    tmp_path: Path,
) -> None:
    supervisor = TransientFailureSupervisor(split_media_info())
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    with pytest.raises(RunnerFailure) as caught:
        await service.inspect(
            "https://www.youtube.com/watch?v=owned",
        )

    assert caught.value.code == "inspection_failed"
    assert caught.value.failure.failure_class.value == "extractor_broken"
    ytdlp = [command for command, _ in supervisor.calls if command[0] == "yt-dlp"]
    assert len(ytdlp) == 1


async def test_inspect_fetches_a_bounded_thumbnail_through_the_proxy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = split_media_info()
    info["thumbnail"] = "https://images.example.com/cover.jpg"
    supervisor = FixtureSupervisor(info)
    clients: list[ThumbnailClient] = []

    def client_factory(**kwargs: object) -> ThumbnailClient:
        client = ThumbnailClient(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(
        "app.workers.runner.thumbnails.httpx.AsyncClient", client_factory
    )
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)

    response = await service.inspect("https://media.example.com/video")

    assert response.media.thumbnail_data_url == "data:image/avif;base64,Y292ZXI="
    assert clients[0].options["proxy"] == "http://egress-proxy:3128"
    assert clients[0].requests == [("GET", "https://images.example.com/cover.jpg")]


async def test_inspect_uses_the_next_thumbnail_candidate_when_the_first_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = split_media_info()
    info["thumbnail"] = "https://images.example.com/unavailable.jpg"
    info["thumbnails"] = [
        {"url": "https://images.example.com/fallback.jpg"},
    ]
    client = ScriptedThumbnailClient(
        [
            ScriptedThumbnailStream(403),
            ScriptedThumbnailStream(200, content=b"fallback"),
        ],
        proxy="unused",
    )
    monkeypatch.setattr(
        "app.workers.runner.thumbnails.httpx.AsyncClient",
        lambda **_: client,
    )
    service = MediaRunnerService(settings(tmp_path), supervisor=FixtureSupervisor(info))

    response = await service.inspect("https://media.example.com/video")

    assert response.media.thumbnail_data_url == ("data:image/jpeg;base64,ZmFsbGJhY2s=")
    assert client.requests == [
        ("GET", "https://images.example.com/unavailable.jpg"),
        ("GET", "https://images.example.com/fallback.jpg"),
    ]


async def test_inspect_retries_a_transient_thumbnail_response_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = split_media_info()
    info["thumbnail"] = "https://images.example.com/cover.jpg"
    client = ScriptedThumbnailClient(
        [ScriptedThumbnailStream(503), ScriptedThumbnailStream(200)],
        proxy="unused",
    )
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(
        "app.workers.runner.thumbnails.httpx.AsyncClient",
        lambda **_: client,
    )
    monkeypatch.setattr("app.workers.runner.thumbnails.asyncio.sleep", record_sleep)
    service = MediaRunnerService(settings(tmp_path), supervisor=FixtureSupervisor(info))

    response = await service.inspect("https://media.example.com/video")

    assert response.media.thumbnail_data_url == "data:image/jpeg;base64,Y292ZXI="
    assert client.requests == [
        ("GET", "https://images.example.com/cover.jpg"),
        ("GET", "https://images.example.com/cover.jpg"),
    ]
    assert delays == [0.25]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/p/fixture/",
        "https://weixin.qq.com/sph/Az42YceBcb",
        "https://v.qq.com/x/page/fixture.html",
        "https://v.youku.com/v_show/id_fixture.html",
    ],
)
async def test_identity_required_provider_is_explicitly_unavailable_in_r0(
    tmp_path, url
):
    supervisor = FixtureSupervisor(split_media_info())
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)
    with pytest.raises(RunnerFailure) as caught:
        await service.inspect(url)
    assert caught.value.code == "login_required"
    assert (
        caught.value.failure.layer
        == service._context(provider_request(url)).resolved_layer
    )
    assert caught.value.failure.stage == "resolve"
    assert supervisor.calls == []
    assert list(tmp_path.iterdir()) == []


async def test_inspection_timeout_cancels_execution_and_removes_workspace(tmp_path):
    cancelled = asyncio.Event()

    class BlockingSupervisor:
        async def run(self, *_args, **_kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    configured = settings(tmp_path).model_copy(
        update={"runner_inspect_timeout_seconds": 0.02}
    )
    service = MediaRunnerService(configured, supervisor=BlockingSupervisor())
    with pytest.raises(RunnerFailure) as caught:
        await service.inspect("https://media.example.com/video")
    assert caught.value.failure.failure_class.value == "transient"
    assert cancelled.is_set()
    assert list(tmp_path.iterdir()) == []


async def test_download_context_mismatch_stops_before_platform_io(tmp_path):
    from dataclasses import replace

    from app.workers.runner.contracts import ExecutionContextContract

    supervisor = FixtureSupervisor(split_media_info())
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)
    request = download_request()
    request.execution_context = ExecutionContextContract.from_domain(
        replace(request.execution_context.to_domain(), resolved_layer="L3")
    )
    with pytest.raises(RunnerFailure) as caught:
        await service.download(request)
    assert caught.value.failure.failure_class.value == "context_changed"
    assert supervisor.calls == []
    assert list(tmp_path.iterdir()) == []


async def test_inspect_resource_cancel_waits_for_cleanup_and_allows_restart(tmp_path):
    started, cleaning, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class BlockingSupervisor:
        async def run(self, *_args, **_kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await finish.wait()

    service = MediaRunnerService(settings(tmp_path), supervisor=BlockingSupervisor())
    task = asyncio.create_task(
        service.inspect("https://media.example.com/video", task_id="parse_intent_0")
    )
    await started.wait()
    assert service._active.status("parse_intent_0") is not None
    with pytest.raises(RunnerFailure, match="task already active"):
        await service.inspect(
            "https://media.example.com/video", task_id="parse_intent_0"
        )
    cancel = asyncio.create_task(service.cancel("parse_intent_0"))
    await cleaning.wait()
    assert not cancel.done()
    finish.set()
    ack = await asyncio.wait_for(cancel, 1)
    assert ack.status == "stopped"
    assert task.cancelled()
    assert service._active.status("parse_intent_0") is None
    assert list(tmp_path.iterdir()) == []
    assert (await service.cancel("parse_intent_0")).status == "stopped"
    service._commands._supervisor = FixtureSupervisor(split_media_info())
    result = await service.inspect(
        "https://media.example.com/video", task_id="parse_intent_0"
    )
    assert result.media.title
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("phase", "stage"),
    [("fetch_metadata", "download"), ("probe_media", "validate")],
)
async def test_download_reinspection_failure_has_download_business_stage(
    tmp_path, phase, stage
):
    from app.services.provider_failures import FailurePhase

    service = MediaRunnerService(settings(tmp_path), supervisor=FixtureSupervisor({}))

    async def fail(*_args, **_kwargs):
        raise RunnerFailure("network_blocked", phase=FailurePhase(phase))

    service._inspection.inspect = fail
    with pytest.raises(RunnerFailure) as caught:
        await service.download(download_request())
    assert caught.value.failure.phase == phase
    assert caught.value.failure.stage == stage
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("category", ["transient", "runtime_unavailable"])
async def test_same_layer_retry_is_bounded_and_cleans_up(tmp_path, category):
    service = MediaRunnerService(settings(tmp_path), supervisor=FixtureSupervisor({}))
    attempts = 0

    async def fail(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise RunnerFailure(category)

    service._inspection.inspect = fail
    with pytest.raises(RunnerFailure) as caught:
        await service.inspect("https://media.example.com/video")
    assert caught.value.code == category
    assert attempts == 2 and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("wait_seconds,expected_attempts", [(0, 2), (0.1, 2), (200, 1)])
async def test_rate_limit_retry_obeys_retry_after_and_original_deadline(
    tmp_path, wait_seconds, expected_attempts
):
    service = MediaRunnerService(settings(tmp_path), supervisor=FixtureSupervisor({}))
    attempts = 0

    async def fail(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise RunnerFailure(
            "rate_limited",
            status=429,
            retry_after=datetime.now(UTC) + timedelta(seconds=wait_seconds),
        )

    service._inspection.inspect = fail
    with pytest.raises(RunnerFailure) as caught:
        await service.inspect(
            "https://media.example.com/video",
            deadline=datetime.now(UTC) + timedelta(seconds=120),
        )
    assert (
        caught.value.code == "rate_limited"
        and caught.value.failure.retry_after is not None
    )
    assert attempts == expected_attempts and list(tmp_path.iterdir()) == []


async def test_zero_deadline_and_cancelling_task_do_not_start_runner_resources(
    tmp_path,
):
    supervisor = FixtureSupervisor(split_media_info())
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)
    with pytest.raises(RunnerFailure, match="inspection timeout"):
        await service.inspect(
            "https://media.example.com/video", deadline=datetime.now(UTC)
        )

    async def cancelled_entry():
        asyncio.current_task().cancel()
        await service.inspect("https://media.example.com/video")

    task = asyncio.create_task(cancelled_entry())
    with pytest.raises(asyncio.CancelledError):
        await task
    assert supervisor.calls == [] and list(tmp_path.iterdir()) == []


@pytest.fixture
def http_only_ladder(monkeypatch):
    """These tests isolate the existing HTTP pipeline, independent of stubs."""
    from dataclasses import replace

    from app.services.provider_types import Layer
    from app.workers.runner.provider_registry import provider_request

    def request(url):
        source = provider_request(url)
        return replace(source, profile=replace(source.profile, ladder=(Layer.L1,)))

    monkeypatch.setattr("app.workers.runner.service.provider_request", request)
