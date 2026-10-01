"""Layer output reusing the normalized media and CandidateStream model."""

from dataclasses import dataclass, field
from typing import Literal

from app.services.provider_failures import ProviderFailure
from app.services.provider_types import ExecutionContext
from app.workers.runner.engine.run_context import RunContext
from app.workers.runner.metadata import MediaInspection


@dataclass(frozen=True, slots=True)
class ResolvedMedia(MediaInspection):
    client: str = "yt-dlp-default"
    handoff: Literal["http", "browser"] = "http"
    run_context: RunContext | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class Resolution:
    media: ResolvedMedia
    execution_context: ExecutionContext
    failures: tuple[ProviderFailure, ...] = ()

    run_context: RunContext | None = field(default=None, repr=False)
