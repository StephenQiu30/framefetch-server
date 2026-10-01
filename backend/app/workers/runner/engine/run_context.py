"""Ephemeral operation materials and injected L1 resources, never persisted."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from app.services.provider_types import ExecutionContext
from app.workers.runner.engine.egress import EgressBinding
from app.workers.runner.provider_registry import ProviderRequest
from app.workers.runner.workspace import TaskWorkspace

if TYPE_CHECKING:
    from app.workers.runner.engine.identity import IdentityMaterial
    from app.workers.runner.inspection_pipeline import RunnerInspectionPipeline


class BrowserHandle(Protocol):
    """Owned browser operation released on completion or cancellation."""

    async def cookies(self) -> list[dict[str, object]]: ...

    @property
    def user_agent(self) -> str: ...

    async def download(self, url: str, dest: Path) -> None: ...

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

    def __post_init__(self) -> None:
        from app.workers.runner.engine.identity import validate_cookie_file

        if self.cookie_file is not None:
            validate_cookie_file(self.cookie_file)
        if self.identity is not None and self.identity.cookie_file != self.cookie_file:
            raise ValueError("identity does not match its cookie file")

    def with_material(
        self,
        *,
        user_agent: str | None = None,
        referer: str | None = None,
        cookie_file: Path | None = None,
        identity: IdentityMaterial | None = None,
        browser: BrowserHandle | None = None,
    ) -> RunContext:
        return replace(
            self,
            user_agent=self.user_agent if user_agent is None else user_agent,
            referer=self.referer if referer is None else referer,
            cookie_file=(
                identity.cookie_file
                if identity is not None
                else self.cookie_file
                if cookie_file is None
                else cookie_file
            ),
            identity=self.identity if identity is None else identity,
            browser=self.browser if browser is None else browser,
        )


@dataclass(frozen=True, slots=True)
class ResolutionSource:
    """Source plus resources owned by the caller's bounded Runner operation."""

    request: ProviderRequest = field(repr=False)
    workspace: TaskWorkspace = field(repr=False)
    pipeline: RunnerInspectionPipeline = field(repr=False)
    execution_context: ExecutionContext
    run_context: RunContext = field(repr=False)

    expected_context: ExecutionContext | None = None
