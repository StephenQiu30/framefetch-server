from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

from app.services.provider_types import ProviderAccessContextRef
from app.workers.runner.contracts import (
    CancelResponse,
    DownloadRequest,
    DownloadResponse,
    InspectResponse,
    MediaSummary,
    ProviderAccessContextContract,
    RunnerTaskStage,
    TaskStatusResponse,
)
from app.workers.runner.settings import RunnerSettings, egress_affinity_id
from app.workers.runner.signing import HmacRequestAuthenticator, InMemoryNonceGuard
from app.workers.runner.version import YTDLP_ENGINE_COMMIT

SECRET = "runner-shared-secret-material-at-least-32-bytes"


class FakeService:
    def __init__(self) -> None:
        self.inspected_url: str | None = None
        self.inspected_context: ProviderAccessContextRef | None = None
        self.inspect_deadline: datetime | None = None
        self.context_requests: list[str] = []
        self.download_request: DownloadRequest | None = None
        self.cancelled: list[str] = []
        self.status_requests: list[str] = []

    async def context(self, url: str) -> ProviderAccessContextRef:
        self.context_requests.append(url)
        return ProviderAccessContextRef.from_document(anonymous_access_context())

    async def contexts_for_providers(
        self, provider_keys: tuple[str, ...]
    ) -> tuple[ProviderAccessContextRef, ...]:
        self.context_requests.extend(provider_keys)
        return tuple(
            ProviderAccessContextRef.from_document(anonymous_access_context())
            for _ in provider_keys
        )

    async def inspect(
        self,
        url: str,
        *,
        access_context: ProviderAccessContextRef | None = None,
        deadline_at: datetime | None = None,
    ) -> InspectResponse:
        self.inspected_url = url
        self.inspected_context = access_context
        self.inspect_deadline = deadline_at
        return InspectResponse(
            media=MediaSummary(
                provider_media_id="fixture-id",
                title="Fixture",
                duration_seconds=60,
                extractor_key="Controlled",
            ),
            streams=[],
            options=[],
            access_context=ProviderAccessContextContract.model_validate(
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
    return {
        "provider_key": "generic",
        "profile_version": "default",
        "access_mode": "anonymous",
        "credential_version_id": None,
        "egress_affinity_id": egress_affinity_id("default", "http://egress-proxy:3128"),
        "client_profile_id": "yt-dlp-default",
        "attestation_provider_version": None,
        "engine_commit": YTDLP_ENGINE_COMMIT,
        "runtime_revision": "a" * 64,
    }


def signed_headers(
    path: str,
    body: bytes,
    nonce: str,
    *,
    method: str = "POST",
) -> dict[str, str]:
    timestamp = int(time.time())
    signer = HmacRequestAuthenticator(
        SECRET.encode(),
        nonce_guard=InMemoryNonceGuard(ttl_seconds=60, max_entries=10),
        max_age_seconds=30,
        max_future_skew_seconds=5,
    )
    signature = signer.sign(method, path, body, timestamp, nonce)
    return {
        "X-Runner-Timestamp": str(timestamp),
        "X-Runner-Nonce": nonce,
        "X-Runner-Signature": signature,
        "Content-Type": "application/json",
    }
