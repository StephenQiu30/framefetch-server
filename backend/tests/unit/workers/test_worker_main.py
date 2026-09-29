from __future__ import annotations

import pytest
from app.core.config import Settings
from app.core.db import create_engine
from app.workers.main import build_components


@pytest.mark.asyncio
async def test_worker_process_builds_every_background_component_lazily() -> None:
    settings = Settings(
        app_env="test",
        service_role="worker",
        session_runner_base_url="http://session-runner:19100",
        _env_file=None,
    )
    # Construction must not connect: Temporal, RabbitMQ and the DB are lazy.
    engine = create_engine(settings.database_url)
    components = build_components(settings, engine)
    try:
        assert set(components) == {"outbox", "download", "import", "report", "canary"}
    finally:
        for component in components.values():
            await component.close()
        await engine.dispose()
