"""Download-capable processes must refuse work before consuming messages."""

from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from app.core.runtime import ApiRuntime, ApiServices
from app.workers.download.runtime import DownloadWorkerRuntime, _serve
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def _drop_execution_column(
    engine: AsyncEngine,
    table: str = "download_jobs",
    column: str = "execution_access_context",
) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))


async def test_api_refuses_to_start_realtime_before_schema_migration(
    postgres_engine: AsyncEngine,
) -> None:
    await _drop_execution_column(postgres_engine)
    realtime = AsyncMock()
    runtime = ApiRuntime(
        services=ApiServices(),
        engine=postgres_engine,
        runner=cast(Any, None),
        auth_session_store=cast(Any, None),
        realtime_consumer=cast(Any, realtime),
    )

    with pytest.raises(RuntimeError, match="download execution schema"):
        await runtime.start()

    realtime.start.assert_not_awaited()


@pytest.mark.parametrize(
    "table,column",
    [
        ("download_jobs", "execution_access_context"),
        ("download_intents", "generation"),
        ("download_intents", "operation_id"),
    ],
)
async def test_download_worker_refuses_to_consume_before_schema_migration(
    postgres_engine: AsyncEngine,
    table: str,
    column: str,
) -> None:
    await _drop_execution_column(postgres_engine, table, column)
    consumer = AsyncMock()
    sweeper = AsyncMock()
    runtime = DownloadWorkerRuntime(
        consumer=cast(Any, consumer),
        inspection_activities=cast(Any, None),
        temporal_address="127.0.0.1:1",
        temporal_namespace="test",
        sweeper=cast(Any, sweeper),
        storage=cast(Any, None),
        runner=cast(Any, None),
        engine=postgres_engine,
    )

    with pytest.raises(RuntimeError, match="download execution schema"):
        await _serve(runtime, asyncio.Event())

    consumer.run.assert_not_awaited()
    sweeper.run.assert_not_awaited()
