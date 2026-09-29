"""Scheduled Provider canary diagnostics inside the worker process."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.core.db import create_session_factory
from app.integrations.media_runner_factory import (
    session_media_runner,
    session_provider_keys,
)
from app.repositories.providers.canary_repository import (
    SqlAlchemyProviderCanaryRepository,
)
from app.repositories.providers.route_cooldowns import SqlAlchemyProviderRouteCooldowns
from app.services.provider_route_admission import ProviderRouteAdmission
from app.services.provider_types import ProviderAccessMode
from app.workers.canary.fixed_cases import fixed_public_diagnostic_targets
from app.workers.canary.runner import ProviderCanaryRunner
from app.workers.canary.scheduler import ProviderCanaryScheduler
from app.workers.canary.service import ProviderCanaryService
from app.workers.canary.targets import (
    parse_canary_targets,
    validate_canary_target_routes,
)
from app.workers.download.workspace import SharedWorkspaceCleaner
from app.workers.runner.provider_registry import configure_provider_instances
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(slots=True)
class ProviderCanaryRuntime:
    scheduler: ProviderCanaryScheduler
    service: ProviderCanaryService
    runner: ProviderCanaryRunner

    async def serve(self, stop: asyncio.Event) -> None:
        await self.scheduler.run(stop)

    async def close(self) -> None:
        await self.runner.close()


def build_runtime(settings: Settings, engine: AsyncEngine) -> ProviderCanaryRuntime:
    configure_provider_instances(settings.peertube_allowed_instances)
    session_keys = session_provider_keys(settings)
    targets = parse_canary_targets(settings.provider_canary_targets)
    if not targets and settings.provider_canary_default_targets:
        # Operator-route samples without a matching session runner cannot run
        # in this deployment; anonymous samples always can.
        targets = tuple(
            target
            for target in fixed_public_diagnostic_targets()
            if target.access_mode is not ProviderAccessMode.OPERATOR_MANAGED
            or target.provider_key in session_keys
        )
    validate_canary_target_routes(targets, session_keys)
    sessions = create_session_factory(engine)
    repository = SqlAlchemyProviderCanaryRepository(sessions)
    admission = ProviderRouteAdmission(SqlAlchemyProviderRouteCooldowns(sessions))
    session_runner = session_media_runner(settings, admission)
    if session_runner is None:
        raise ValueError("SESSION_RUNNER_BASE_URL is required")
    runner = ProviderCanaryRunner(session_runner)
    service = ProviderCanaryService(
        repository,
        runner,
        SharedWorkspaceCleaner(settings.runner_workspace_root),
        now=_utc_now,
    )
    return ProviderCanaryRuntime(
        scheduler=ProviderCanaryScheduler(
            repository,
            service,
            targets,
            metadata_interval=timedelta(
                seconds=settings.provider_canary_metadata_interval_seconds
            ),
            media_interval=timedelta(
                seconds=settings.provider_canary_media_interval_seconds
            ),
            poll_seconds=settings.provider_canary_poll_seconds,
            now=_utc_now,
        ),
        service=service,
        runner=runner,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)
