from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aio_pika
import httpx
import pytest
from app.core.config import Settings
from app.integrations.readiness import (
    AsyncCheck,
    assert_download_execution_schema,
    build_runtime_readiness,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class FakeConnection:
    async def close(self) -> None:
        return None


@pytest.fixture
def rabbitmq_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    async def connect(
        url: str,
        *,
        timeout: float,
        client_properties: dict[str, str],
    ) -> FakeConnection:
        assert url == "amqp://user:redacted@rabbit.test:5672/"
        assert timeout == 1
        assert client_properties["connection_name"] == "video-server-api-readiness"
        return FakeConnection()

    monkeypatch.setattr(aio_pika, "connect", connect)


@asynccontextmanager
async def runtime_probe(
    handler: httpx.AsyncBaseTransport,
    engine: AsyncEngine,
    *,
    operator_runners: dict[str, str] | None = None,
    redis_check: AsyncCheck | None = None,
) -> AsyncIterator[Any]:
    client = httpx.AsyncClient(transport=handler)
    settings = Settings(
        app_env="test",
        _env_file=None,
        database_url=str(engine.url),
        rabbitmq_url="amqp://user:redacted@rabbit.test:5672/",
        runner_operator_base_urls=operator_runners or {},
        minio_endpoint="minio.test:9000",
        readiness_timeout_seconds=1,
    )
    probe = build_runtime_readiness(
        settings, engine, client=client, redis_check=redis_check
    )
    try:
        yield probe
    finally:
        await probe.close()


@pytest.mark.usefixtures("rabbitmq_is_available")
async def test_runtime_readiness_checks_database_minio_and_rabbitmq(
    postgres_engine: AsyncEngine,
) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path in {"/health/ready", "/minio/health/live"}
        return httpx.Response(200)

    async with runtime_probe(httpx.MockTransport(respond), postgres_engine) as probe:
        assert await probe.check() is True


@pytest.mark.usefixtures("rabbitmq_is_available")
async def test_runtime_readiness_fails_closed_without_exposing_dependency_error(
    postgres_engine: AsyncEngine,
) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        status = 503 if request.url.host == "minio.test" else 200
        return httpx.Response(status)

    async with runtime_probe(httpx.MockTransport(respond), postgres_engine) as probe:
        assert await probe.check() is False


@pytest.mark.usefixtures("rabbitmq_is_available")
async def test_runtime_readiness_does_not_contact_media_runners(
    postgres_engine: AsyncEngine,
) -> None:
    seen: set[str] = set()

    async def respond(request: httpx.Request) -> httpx.Response:
        seen.add(request.url.host or "")
        return httpx.Response(200)

    async with runtime_probe(
        httpx.MockTransport(respond),
        postgres_engine,
        operator_runners={"x": "http://x-runner.test"},
    ) as probe:
        assert await probe.check() is True

    assert "runner.test" not in seen
    assert "minio.test" in seen
    assert "x-runner.test" not in seen


@pytest.mark.usefixtures("rabbitmq_is_available")
async def test_runtime_readiness_survives_all_runners_being_unreachable(
    postgres_engine: AsyncEngine,
) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host != "minio.test":
            raise httpx.ConnectError("runner offline", request=request)
        return httpx.Response(200)

    async with runtime_probe(
        httpx.MockTransport(respond),
        postgres_engine,
        operator_runners={"x": "http://x-runner.test"},
    ) as probe:
        assert await probe.check() is True


@pytest.mark.usefixtures("rabbitmq_is_available")
async def test_runtime_readiness_checks_the_active_postgres_schema(
    postgres_engine: AsyncEngine,
) -> None:
    async with postgres_engine.begin() as connection:
        await connection.execute(text("DROP TABLE document_artifacts CASCADE"))

    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async with runtime_probe(httpx.MockTransport(respond), postgres_engine) as probe:
        assert await probe.check() is False


@pytest.mark.usefixtures("rabbitmq_is_available")
@pytest.mark.parametrize("column", ["execution_context", "execution_context_attempt"])
async def test_runtime_readiness_rejects_missing_download_execution_column(
    postgres_engine: AsyncEngine, column: str
) -> None:
    async with postgres_engine.begin() as connection:
        await connection.execute(
            text(f"ALTER TABLE download_jobs DROP COLUMN {column}")
        )

    async with runtime_probe(
        httpx.MockTransport(lambda _: httpx.Response(200)), postgres_engine
    ) as probe:
        assert await probe.check() is False
    with pytest.raises(RuntimeError, match="download execution schema"):
        await assert_download_execution_schema(postgres_engine)


@pytest.mark.usefixtures("rabbitmq_is_available")
async def test_runtime_readiness_rejects_wrong_download_execution_column_type(
    postgres_engine: AsyncEngine,
) -> None:
    async with postgres_engine.begin() as connection:
        await connection.execute(
            text(
                "ALTER TABLE download_jobs ALTER COLUMN execution_context_attempt "
                "TYPE BIGINT"
            )
        )

    async with runtime_probe(
        httpx.MockTransport(lambda _: httpx.Response(200)), postgres_engine
    ) as probe:
        assert await probe.check() is False
    with pytest.raises(RuntimeError, match="download execution schema"):
        await assert_download_execution_schema(postgres_engine)


@pytest.mark.usefixtures("rabbitmq_is_available")
async def test_runtime_readiness_does_not_depend_on_analysis_worker(
    postgres_engine: AsyncEngine,
) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async with runtime_probe(httpx.MockTransport(respond), postgres_engine) as probe:
        assert await probe.check() is True


@pytest.mark.usefixtures("rabbitmq_is_available")
@pytest.mark.parametrize("dependency", ["rabbitmq", "redis"])
async def test_core_dependency_failure_still_rejects_readiness(
    postgres_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, dependency: str
) -> None:
    async def unavailable(*_args: object, **_kwargs: object) -> None:
        raise ConnectionError("core dependency offline")

    if dependency == "rabbitmq":
        monkeypatch.setattr(aio_pika, "connect", unavailable)
    async with runtime_probe(
        httpx.MockTransport(lambda _: httpx.Response(200)),
        postgres_engine,
        redis_check=unavailable if dependency == "redis" else None,
    ) as probe:
        assert await probe.check() is False
