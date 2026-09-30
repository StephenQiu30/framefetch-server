from __future__ import annotations

from pathlib import Path

from app.services.provider_types import ProviderAccessMode
from app.workers.runner.contracts import DownloadRequest
from app.workers.runner.process import ProcessResult
from app.workers.runner.release_identity import runtime_code_sha256
from app.workers.runner.settings import RunnerSettings, egress_affinity_id
from app.workers.runner.version import YTDLP_ENGINE_COMMIT

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
            "access_context": {
                "provider_key": "generic",
                "profile_version": "default",
                "access_mode": "anonymous",
                "credential_version_id": None,
                "egress_affinity_id": egress_affinity_id(
                    "default", "http://egress-proxy:3128"
                ),
                "client_profile_id": "yt-dlp-default",
                "attestation_provider_version": None,
                "engine_commit": YTDLP_ENGINE_COMMIT,
                "runtime_revision": runtime_code_sha256(
                    "generic", access_mode=ProviderAccessMode.ANONYMOUS
                ),
                "strategy_id": "yt-dlp-anonymous",
                "adapter_revision": "default",
                "session_source_id": None,
                "browser_context_revision": None,
                "protocol_capabilities": ["http-media"],
                "egress_observation_ref": None,
            },
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
