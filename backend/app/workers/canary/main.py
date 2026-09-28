"""Run with: python -m app.workers.canary.main."""

from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import Settings, get_settings_for_role
from app.core.db import create_engine, create_session_factory
from app.integrations.media_runner_factory import (
    anonymous_media_runner,
    guest_media_runners,
    session_media_runner,
    session_provider_keys,
)
from app.repositories.providers.canary_repository import (
    SqlAlchemyProviderCanaryRepository,
)
from app.repositories.providers.guest_contexts import GuestContexts
from app.repositories.providers.route_cooldowns import SqlAlchemyProviderRouteCooldowns
from app.services.provider_route_admission import ProviderRouteAdmission
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
    engine: AsyncEngine

    async def close(self) -> None:
        try:
            await self.runner.close()
        finally:
            await self.engine.dispose()


def build_runtime(settings: Settings) -> ProviderCanaryRuntime:
    configure_provider_instances(settings.peertube_allowed_instances)
    targets = parse_canary_targets(settings.provider_canary_targets)
    validate_canary_target_routes(
        targets,
        session_provider_keys(settings),
        guest_provider_keys=frozenset(
            provider.value for provider in settings.runner_guest_base_urls
        ),
    )
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    repository = SqlAlchemyProviderCanaryRepository(sessions)
    admission = ProviderRouteAdmission(SqlAlchemyProviderRouteCooldowns(sessions))
    anonymous = anonymous_media_runner(settings, admission)
    runner = ProviderCanaryRunner(
        anonymous,
        session_media_runner(settings, admission),
        guests=guest_media_runners(settings, admission, GuestContexts(sessions).reject),
    )
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
        engine=engine,
    )


async def run() -> None:
    runtime = build_runtime(get_settings_for_role("provider-canary"))
    stop = asyncio.Event()
    _install_signal_handlers(stop)
    try:
        await runtime.scheduler.run(stop)
    finally:
        await asyncio.shield(runtime.close())


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for requested_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(requested_signal, stop.set)
        except NotImplementedError:
            pass


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
