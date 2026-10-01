"""Ephemeral operation materials and injected L1 resources, never persisted."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from app.services.provider_types import ExecutionContext
from app.workers.runner.engine.egress import EgressBinding
from app.workers.runner.inspection_pipeline import RunnerInspectionPipeline
from app.workers.runner.provider_registry import ProviderRequest
from app.workers.runner.workspace import TaskWorkspace

if TYPE_CHECKING:
    from app.workers.runner.engine.identity import IdentityMaterial


class BrowserHandle(Protocol):
    """Owned browser operation released on completion or cancellation."""

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RunContext:
    egress: EgressBinding
    user_agent: str
    referer: str
    cookie_file: Path | None = field(repr=False)
    identity: IdentityMaterial | None = field(repr=False)
    browser: BrowserHandle | None = field(repr=False)
    deadline: datetime


@dataclass(frozen=True, slots=True)
class ResolutionSource:
    """Source plus resources owned by the caller's bounded Runner operation."""

    request: ProviderRequest = field(repr=False)
    workspace: TaskWorkspace = field(repr=False)
    pipeline: RunnerInspectionPipeline = field(repr=False)
    execution_context: ExecutionContext
    run_context: RunContext = field(repr=False)
