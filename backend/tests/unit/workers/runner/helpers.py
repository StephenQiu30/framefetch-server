from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.workers.runner.contracts import DownloadRequest
from app.workers.runner.process import ProcessResult
from app.workers.runner.provider_registry import provider_request
from app.workers.runner.service import MediaRunnerService
from app.workers.runner.settings import RunnerSettings

SECRET = "runner-shared-secret-material-at-least-32-bytes"


def split_media_info(height: int = 1080) -> dict[str, object]:
    return {
        "id": "controlled",
        "title": "Controlled",
        "duration": 30,
        "extractor_key": "Controlled",
        "webpage_url": "https://media.example.com/video",
        "live_status": "not_live",
        "formats": [
            {
                "format_id": "video",
                "ext": "mp4",
                "width": 1920 if height == 1080 else 1280,
                "height": height,
                "fps": 30,
                "vcodec": "avc1.640028",
                "acodec": "none",
            },
            {
                "format_id": "audio",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "language": "zh-CN",
            },
        ],
    }


def result(stdout: bytes = b"") -> ProcessResult:
    return ProcessResult(0, stdout, b"", False, False)


def settings(tmp_path: Path) -> RunnerSettings:
    return RunnerSettings(
        runner_hmac_secret=SECRET,
        runner_egress_proxy="http://egress-proxy:3128",
        runner_global_egress_proxy="http://egress-proxy:3128",
        runner_workspace_root=tmp_path,
        runner_ytdlp_bin="yt-dlp",
        runner_ffmpeg_bin="ffmpeg",
        runner_ffprobe_bin="ffprobe",
    )


def download_request(height: int = 1080, width: int = 1920) -> DownloadRequest:
    return DownloadRequest.model_validate(
        {
            "task_id": "job_123",
            "url": "https://media.example.com/video",
            "expected_provider_media_id": "controlled",
            "expected_extractor_key": "Controlled",
            "expected_duration_seconds": 30,
            "issued_at": datetime.now(UTC).isoformat(),
            "deadline": (datetime.now(UTC) + timedelta(seconds=600)).isoformat(),
            "execution_context": MediaRunnerService(
                settings(Path("/tmp/runner-fixture"))
            )
            ._context(provider_request("https://media.example.com/video"))
            .to_document(),
            "plan": {
                "height": height,
                "width": width,
                "fps_bucket": "fps_30",
                "dynamic_range": "sdr",
                "video_codec_family": "h264",
                "audio_codec_family": "aac",
                "audio_language": "zh-CN",
                "container_preference": "mp4",
                "compatibility_profile": "balanced",
                "hints": {"video_id": "stale", "audio_id": "stale"},
            },
        }
    )


def run_context(config: RunnerSettings, provider: str = "generic"):
    from app.workers.runner.engine.egress import resolve_egress
    from app.workers.runner.engine.run_context import RunContext
    from app.workers.runner.provider_registry import current_provider_registry

    return RunContext(
        resolve_egress(
            current_provider_registry().profile_for_key(provider), settings=config
        ),
        "",
        "",
        None,
        None,
        None,
        datetime.now(UTC) + timedelta(seconds=120),
    )


def bound_commands(config, supervisor, **kwargs):
    from app.workers.runner.commands import MediaCommands

    provider = "youtube" if config.runner_global_egress_proxy else "generic"
    return MediaCommands(config, supervisor, **kwargs).with_context(
        run_context(config, provider)
    )


def bound_builder(config, root):
    from app.workers.runner.yt_dlp_commands import YtDlpCommandBuilder

    return YtDlpCommandBuilder(config, root, run_context(config))
