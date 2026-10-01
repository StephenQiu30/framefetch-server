from __future__ import annotations

import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.services.provider_types import ExecutionContext
from app.workers.runner.contracts import (
    CancelResponse,
    DownloadRequest,
    DownloadResponse,
    ExecutionContextContract,
    InspectResponse,
    MediaSummary,
    RunnerTaskStage,
    TaskStatusResponse,
)
from app.workers.runner.provider_registry import provider_request
from app.workers.runner.service import MediaRunnerService
from app.workers.runner.settings import RunnerSettings
from app.workers.runner.signing import HmacRequestAuthenticator, InMemoryNonceGuard

SECRET = "runner-shared-secret-material-at-least-32-bytes"


class FakeService:
    def __init__(self) -> None:
        self.inspected_url: str | None = None
        self.inspected_context: ExecutionContext | None = None
        self.download_request: DownloadRequest | None = None
        self.cancelled: list[str] = []
        self.status_requests: list[str] = []

    async def inspect(
        self,
        url: str,
        *,
        execution_context: ExecutionContext | None = None,
        task_id: str | None = None,
        deadline: datetime | None = None,
    ) -> InspectResponse:
        self.inspected_url = url
        self.inspected_context = execution_context
        return InspectResponse(
            media=MediaSummary(
                provider_media_id="fixture-id",
                title="Fixture",
                duration_seconds=60,
                extractor_key="Controlled",
            ),
            streams=[],
            options=[],
            execution_context=ExecutionContextContract.model_validate(
                anonymous_access_context()
            ),
        )

    async def download(self, request: DownloadRequest) -> DownloadResponse:
        self.download_request = request
        return DownloadResponse.model_validate(
            {
                "task_id": request.task_id,
                "workspace_path": "/shared/job",
                "artifact": {
                    "relative_path": "artifact.mp4",
                    "size_bytes": 5,
                    "sha256": "a" * 64,
                    "duration_seconds": 60,
                    "container": "mp4",
                    "video_streams": 1,
                    "audio_streams": 1,
                },
            }
        )

    async def cancel(self, task_id: str) -> CancelResponse:
        self.cancelled.append(task_id)
        return CancelResponse(task_id=task_id)

    async def status(self, task_id: str) -> TaskStatusResponse:
        self.status_requests.append(task_id)
        return TaskStatusResponse(
            task_id=task_id,
            stage=RunnerTaskStage.DOWNLOADING,
            progress=40,
        )


def settings(tmp_path: Path) -> RunnerSettings:
    return RunnerSettings(
        runner_hmac_secret=SECRET,
        runner_egress_proxy="http://egress-proxy:3128",
        runner_workspace_root=tmp_path,
        runner_ytdlp_bin=str(Path(sys.executable).parent / "yt-dlp"),
    )


def anonymous_access_context() -> dict[str, object]:
    configured = settings(Path("/tmp/runner-fixture"))
    return (
        MediaRunnerService(configured)
        ._context(provider_request("https://media.example.com/video"))
        .to_document()
    )


def inspect_document(url: str, **facts) -> dict[str, object]:
    return {
        "task_id": "parse_fixture",
        "deadline": (datetime.now(UTC) + timedelta(seconds=120)).isoformat(),
        "issued_at": datetime.now(UTC).isoformat(),
        "url": url,
        "execution_context": anonymous_access_context(),
        **facts,
    }


def signed_headers(
    path: str,
    body: bytes,
    nonce: str,
    *,
    method: str = "POST",
    instance_id: str = "0" * 32,
) -> dict[str, str]:
    timestamp = int(time.time())
    signer = HmacRequestAuthenticator(
        SECRET.encode(),
        nonce_guard=InMemoryNonceGuard(ttl_seconds=60, max_entries=10),
        max_age_seconds=30,
        max_future_skew_seconds=5,
    )
    instance = (
        instance_id
        if path in {"/internal/inspect", "/internal/download"}
        or path.endswith("/cancel")
        else None
    )
    signature = signer.sign(
        method, path, body, timestamp, nonce, runtime_instance_id=instance
    )
    return {
        "X-Runner-Timestamp": str(timestamp),
        "X-Runner-Nonce": nonce,
        "X-Runner-Signature": signature,
        "Content-Type": "application/json",
        **({"X-Runner-Instance": instance} if instance is not None else {}),
    }
