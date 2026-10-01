"""Shared real-service fixtures for integration tests."""

import os
import shutil
from datetime import timedelta

import pytest
from app.core.config import Settings
from temporalio.api.workflowservice.v1 import RegisterNamespaceRequest
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment


@pytest.fixture
async def temporal_client():
    address = os.environ.get("TEST_TEMPORAL_ADDRESS")
    if not address and os.environ.get("TEST_TEMPORAL_START_LOCAL") == "true":
        async with await WorkflowEnvironment.start_local(
            namespace="framefetch-test",
            dev_server_existing_path=shutil.which("temporal"),
            dev_server_download_version="v1.8.2",
        ) as environment:
            yield environment.client
        return
    client = await Client.connect(
        address or Settings().temporal_address, namespace="framefetch-test"
    )
    request = RegisterNamespaceRequest(namespace="framefetch-test")
    request.workflow_execution_retention_period.FromTimedelta(timedelta(days=1))
    try:
        await client.workflow_service.register_namespace(request)
    except RPCError as exc:
        if exc.status != RPCStatusCode.ALREADY_EXISTS:
            raise
    yield client
