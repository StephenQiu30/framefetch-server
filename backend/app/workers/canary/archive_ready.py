"""Fail unless every registered Provider has current verified status."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from app.core.config import get_settings_for_role
from app.core.db import create_engine, create_session_factory
from app.integrations.media_runner_factory import (
    media_runner_router,
    session_provider_keys,
)
from app.integrations.provider_status import configured_provider_statuses
from app.integrations.site_session_catalog import SiteSessionRoutes
from app.repositories.providers.canary_repository import (
    SqlAlchemyProviderCanaryRepository,
)
from app.repositories.providers.site_sessions import SiteSessionStates
from app.services.provider_canaries import ProviderStatusService
from app.services.provider_types import ProviderSupportStatus
from app.workers.runner.provider_registry import configure_provider_instances


async def pending_provider_statuses() -> tuple[dict[str, str], ...]:
    settings = get_settings_for_role("provider-canary")
    configure_provider_instances(settings.peertube_allowed_instances)
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    runner = media_runner_router(
        settings, session_routes=SiteSessionRoutes(SiteSessionStates(sessions))
    )
    service = ProviderStatusService(
        SqlAlchemyProviderCanaryRepository(sessions),
        configured_provider_statuses(
            session_provider_keys(settings),
        ),
        now=lambda: datetime.now(UTC),
        context_reader=runner,
        approved_keys=settings.provider_verified_keys,
    )
    try:
        views = await service.list()
    finally:
        await runner.close()
        await engine.dispose()
    return tuple(
        {"key": item.key, "status": item.status.value}
        for item in views
        if item.registered and item.status is not ProviderSupportStatus.VERIFIED
    )


async def _run() -> int:
    pending = await pending_provider_statuses()
    print(
        json.dumps(
            {"archive_ready": not pending, "pending": pending},
            separators=(",", ":"),
        )
    )
    return 0 if not pending else 1


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
