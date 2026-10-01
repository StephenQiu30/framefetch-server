"""Local integration tests must reuse the configured Temporal service."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

SCRIPT = Path(__file__).parents[1] / "integration/conftest.py"
SPEC = importlib.util.spec_from_file_location("temporal_test_fixtures", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
fixtures = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixtures)


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [None, "existing-temporal:7233"])
async def test_default_and_explicit_address_never_start_another_server(
    monkeypatch, override
):
    monkeypatch.delenv("TEST_TEMPORAL_ADDRESS", raising=False)
    monkeypatch.delenv("TEST_TEMPORAL_START_LOCAL", raising=False)
    if override:
        monkeypatch.setenv("TEST_TEMPORAL_ADDRESS", override)
    monkeypatch.setattr(
        fixtures,
        "Settings",
        lambda: SimpleNamespace(temporal_address="127.0.0.1:7233"),
        raising=False,
    )
    client = SimpleNamespace(
        workflow_service=SimpleNamespace(register_namespace=AsyncMock())
    )
    connect = AsyncMock(return_value=client)
    start = AsyncMock(side_effect=AssertionError("unexpected Temporal startup"))
    monkeypatch.setattr(fixtures.Client, "connect", connect)
    monkeypatch.setattr(fixtures.WorkflowEnvironment, "start_local", start)

    generator = fixtures.temporal_client.__wrapped__()
    assert await anext(generator) is client
    await generator.aclose()

    connect.assert_awaited_once_with(
        override or "127.0.0.1:7233", namespace="framefetch-test"
    )
    start.assert_not_awaited()
    request = client.workflow_service.register_namespace.await_args.args[0]
    assert request.namespace == "framefetch-test"


@pytest.mark.asyncio
async def test_ci_can_explicitly_start_an_isolated_test_server(monkeypatch):
    monkeypatch.delenv("TEST_TEMPORAL_ADDRESS", raising=False)
    monkeypatch.setenv("TEST_TEMPORAL_START_LOCAL", "true")
    client = object()

    class Environment:
        async def __aenter__(self):
            return SimpleNamespace(client=client)

        async def __aexit__(self, *_args):
            return False

    start = AsyncMock(return_value=Environment())
    connect = AsyncMock(side_effect=AssertionError("unexpected external connection"))
    monkeypatch.setattr(fixtures.WorkflowEnvironment, "start_local", start)
    monkeypatch.setattr(fixtures.Client, "connect", connect)

    generator = fixtures.temporal_client.__wrapped__()
    assert await anext(generator) is client
    await generator.aclose()

    assert start.await_args.kwargs["namespace"] == "framefetch-test"
    connect.assert_not_awaited()
