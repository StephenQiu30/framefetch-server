"""Bounded dependency probes used by the API readiness endpoint."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import aio_pika
import httpx
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

import app.models  # noqa: F401  # Register the complete SQLAlchemy metadata graph.
from app.core.config import Settings
from app.core.db import Base

AsyncCheck = Callable[[], Awaitable[None]]
EXPECTED_DATABASE_TABLES = frozenset(Base.metadata.tables)
_DATABASE_TABLES_QUERY = text(
    """
    SELECT tablename
    FROM pg_catalog.pg_tables
    WHERE schemaname = current_schema() AND tablename IN :expected_tables
    """
).bindparams(bindparam("expected_tables", expanding=True))
_DOWNLOAD_EXECUTION_COLUMNS = {
    "execution_access_context": "jsonb",
    "execution_context_attempt": "integer",
}
_DOWNLOAD_EXECUTION_COLUMNS_QUERY = text(
    """
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = :table_name
      AND column_name IN :expected_columns
    """
).bindparams(bindparam("expected_columns", expanding=True))


async def assert_download_execution_schema(engine: AsyncEngine) -> None:
    """Fail process startup before API traffic or download queue consumers run."""
    async with engine.connect() as connection:
        await _assert_download_execution_columns(connection)


async def _assert_download_execution_columns(connection: AsyncConnection) -> None:
    for table, expected in (
        ("download_jobs", _DOWNLOAD_EXECUTION_COLUMNS),
        (
            "download_intents",
            {"generation": "integer", "operation_id": "character varying"},
        ),
    ):
        columns = await connection.execute(
            _DOWNLOAD_EXECUTION_COLUMNS_QUERY,
            {"expected_columns": tuple(expected), "table_name": table},
        )
        if dict(columns.tuples().all()) != expected:
            raise RuntimeError("database download execution schema is incompatible")


class RuntimeReadiness:
    def __init__(
        self,
        checks: tuple[AsyncCheck, ...],
        client: httpx.AsyncClient,
        *,
        timeout_seconds: float,
    ) -> None:
        self._checks = checks
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def check(self) -> bool:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                results = await asyncio.gather(
                    *(check() for check in self._checks),
                    return_exceptions=True,
                )
        except TimeoutError:
            return False
        return all(result is None for result in results)

    async def close(self) -> None:
        await self._client.aclose()


def build_runtime_readiness(
    settings: Settings,
    engine: AsyncEngine,
    *,
    client: httpx.AsyncClient | None = None,
    redis_check: AsyncCheck | None = None,
) -> RuntimeReadiness:
    http_client = client or httpx.AsyncClient(
        timeout=settings.readiness_timeout_seconds,
        follow_redirects=False,
    )
    minio_scheme = "https" if settings.minio_internal_secure else "http"
    minio_url = (
        f"{minio_scheme}://{settings.minio_endpoint.rstrip('/')}/minio/health/live"
    )

    async def database_check() -> None:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            result = await connection.execute(
                _DATABASE_TABLES_QUERY,
                {"expected_tables": tuple(sorted(EXPECTED_DATABASE_TABLES))},
            )
            found_tables = set(result.scalars())
            if found_tables != EXPECTED_DATABASE_TABLES:
                missing = ", ".join(sorted(EXPECTED_DATABASE_TABLES - found_tables))
                raise RuntimeError(f"database schema is incomplete: {missing}")
            await _assert_download_execution_columns(connection)

    async def http_check(url: str) -> None:
        response = await http_client.get(url)
        response.raise_for_status()

    async def rabbitmq_check() -> None:
        connection = await aio_pika.connect(
            settings.rabbitmq_url,
            timeout=settings.readiness_timeout_seconds,
            client_properties={"connection_name": "video-server-api-readiness"},
        )
        await connection.close()

    checks: list[AsyncCheck] = [
        database_check,
        lambda: http_check(minio_url),
        rabbitmq_check,
    ]
    # Media Runner and analysis worker health are feature-level information.
    # Core APIs stay available while media services recover.
    if redis_check is not None:
        checks.append(redis_check)
    return RuntimeReadiness(
        tuple(checks),
        http_client,
        timeout_seconds=settings.readiness_timeout_seconds,
    )
