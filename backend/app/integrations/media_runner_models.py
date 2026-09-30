"""Infrastructure-owned results returned by the Media Runner client."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.services.downloads.rules.enums import DownloadStage, MediaKind
from app.services.provider_failures import ProviderFailure
from app.workers.runner.contracts import RunnerTaskStage


class MediaRunnerClientError(RuntimeError):
    def __init__(
        self,
        code: str,
        status: int,
        *,
        retry_at: datetime | None = None,
        failure: ProviderFailure | None = None,
    ) -> None:
        self.code = code
        self.status = status
        self.retry_at = retry_at
        self.failure = failure or ProviderFailure.for_code(code, retry_after=retry_at)
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RunnerArtifact:
    task_id: str
    workspace: Path
    artifact: Path
    size_bytes: int
    sha256: str
    duration_seconds: float
    container: str
    video_streams: int
    audio_streams: int
    media_kind: MediaKind = MediaKind.VIDEO
    asset_count: int = 0


@dataclass(frozen=True, slots=True)
class RunnerProgress:
    stage: DownloadStage
    progress: int


def download_stage(value: RunnerTaskStage) -> DownloadStage:
    if value is RunnerTaskStage.READY:
        return DownloadStage.VERIFYING
    return DownloadStage(value.value)
