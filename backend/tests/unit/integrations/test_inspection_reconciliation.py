"""Signed HTTP receipts recover lost replies without a second platform call."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.integrations.media_runner import MediaRunnerHttpClient
from app.services.downloads.errors import MediaInspectionTemporarilyUnavailable
from app.services.downloads.resolution import ResolutionExecution, ResolutionPlan
from app.services.provider_failures import FailureClass
from app.workers.runner.main import create_app
from app.workers.runner.process import ProcessResult
from app.workers.runner.provider_registry import provider_profile
from app.workers.runner.resolution_catalog import resolution_capability
from app.workers.runner.service import MediaRunnerService
from tests.unit.workers.runner.helpers import SECRET, settings, split_media_info

URL = "https://commons.wikimedia.org/wiki/File:Big_buck_bunny_mcu.ogv"


class FixtureSupervisor:
    def __init__(self, info):
        self.info = {**info, "webpage_url": URL, "extractor_key": "Wikimedia"}
        self.calls = []

    async def run(self, argv, **_kwargs):
        assert "--dump-single-json" in argv
        self.calls.append(tuple(argv))
        return ProcessResult(0, json.dumps(self.info).encode(), b"", False, False)


class LoseInspectReply(httpx.AsyncBaseTransport):
    def __init__(self, app):
        self.inner = httpx.ASGITransport(app=app)
        self.calls = []

    async def handle_async_request(self, request):
        self.calls.append(request.url.path)
        response = await self.inner.handle_async_request(request)
        if request.url.path == "/internal/inspect":
            assert response.status_code == 200
            await response.aclose()
            raise httpx.ReadError("response lost", request=request)
        return response


async def test_lost_signed_reply_reads_original_success_and_never_resubmits(tmp_path):
    configured = settings(tmp_path)
    supervisor = FixtureSupervisor(split_media_info())
    service = MediaRunnerService(configured, supervisor=supervisor)
    transport = LoseInspectReply(create_app(configured, service=service))
    plan = ResolutionPlan(resolution_capability(provider_profile(URL), configured), 0)
    async with httpx.AsyncClient(base_url="http://runner", transport=transport) as http:
        client = MediaRunnerHttpClient(
            base_url="http://runner",
            secret=SECRET.encode(),
            workspace_root=tmp_path,
            inspect_timeout_seconds=5,
            download_timeout_seconds=5,
            client=http,
        )
        prepared = await client.prepare_resolution(
            URL, plan, plan.first_strategy.strategy_id
        )
        execution = ResolutionExecution(
            plan.first_strategy.strategy_id,
            plan.revision,
            "a" * 64,
            prepared.context,
            prepared.runner_instance_id,
            datetime.now(UTC) + timedelta(seconds=30),
        )
        recovered = await client.inspect(URL, execution=execution)
        assert recovered.access_context == execution.context
        assert recovered.provider_media_id == "controlled"
        repeated = await client.reconcile_inspection(URL, execution)
        assert repeated == recovered
        assert await client.cancel_inspection(execution)
    assert transport.calls.count("/internal/inspect") == 1
    assert len(supervisor.calls) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("receipt", ["active", "outcome_unknown", "wrong_boot"])
async def test_unconfirmed_owner_never_authorizes_replacement(tmp_path, receipt):
    configured = settings(tmp_path)
    service = MediaRunnerService(
        configured, supervisor=FixtureSupervisor(split_media_info())
    )
    context = await service.context(URL)
    plan = ResolutionPlan(resolution_capability(provider_profile(URL), configured), 0)
    execution = ResolutionExecution(
        context.strategy_id,
        plan.revision,
        "a" * 64,
        context,
        "b" * 32,
        datetime.now(UTC) - timedelta(seconds=1),
    )
    calls = []

    async def respond(request):
        calls.append(request.url.path)
        assert request.url.path.startswith("/internal/inspection-operations/")
        assert request.headers["X-Runner-Instance"] == execution.runner_instance_id
        if receipt == "wrong_boot":
            return httpx.Response(409, json={"error": {"code": "runner_restarted"}})
        if request.method == "POST":
            assert json.loads(request.content) == {}
        return httpx.Response(200, json={"status": receipt})

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        client = MediaRunnerHttpClient(
            base_url="http://runner",
            secret=SECRET.encode(),
            workspace_root=tmp_path,
            inspect_timeout_seconds=5,
            download_timeout_seconds=5,
            client=http,
        )
        with pytest.raises(MediaInspectionTemporarilyUnavailable) as caught:
            await client.reconcile_inspection(URL, execution)
        assert caught.value.failure.failure_class is FailureClass.OUTCOME_UNKNOWN
        assert not await client.cancel_inspection(execution)
    assert "/internal/inspect" not in calls


async def test_receipt_with_changed_context_is_rejected(tmp_path):
    configured = settings(tmp_path)
    supervisor = FixtureSupervisor(split_media_info())
    service = MediaRunnerService(configured, supervisor=supervisor)
    inspected = await service.inspect(URL)
    context = inspected.access_context.to_domain()
    plan = ResolutionPlan(resolution_capability(provider_profile(URL), configured), 0)
    execution = ResolutionExecution(
        context.strategy_id,
        plan.revision,
        "a" * 64,
        replace(context, engine_commit="changed"),
        "b" * 32,
        datetime.now(UTC) + timedelta(seconds=30),
    )

    async def respond(_request):
        return httpx.Response(
            200,
            json={"status": "succeeded", "result": inspected.model_dump(mode="json")},
        )

    from app.services.downloads.errors import MediaInspectionFailure

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        client = MediaRunnerHttpClient(
            base_url="http://runner",
            secret=SECRET.encode(),
            workspace_root=tmp_path,
            inspect_timeout_seconds=5,
            download_timeout_seconds=5,
            client=http,
        )
        with pytest.raises(MediaInspectionFailure) as caught:
            await client.reconcile_inspection(URL, execution)
        assert caught.value.failure.failure_class is FailureClass.CONTEXT_CHANGED
    assert len(supervisor.calls) == 1


async def test_active_receipt_can_finish_without_cancellation_or_another_inspect(
    tmp_path,
):
    configured = settings(tmp_path)
    supervisor = FixtureSupervisor(split_media_info())
    service = MediaRunnerService(configured, supervisor=supervisor)
    inspected = await service.inspect(URL)
    context = inspected.access_context.to_domain()
    plan = ResolutionPlan(resolution_capability(provider_profile(URL), configured), 0)
    execution = ResolutionExecution(
        context.strategy_id,
        plan.revision,
        "a" * 64,
        context,
        "b" * 32,
        datetime.now(UTC) + timedelta(seconds=30),
    )
    calls = []

    async def respond(request):
        calls.append(request.url.path)
        assert request.method == "GET"  # A healthy owner is never cancelled.
        return httpx.Response(
            200,
            json={"status": "active"}
            if len(calls) == 1
            else {
                "status": "succeeded",
                "result": inspected.model_dump(mode="json"),
            },
        )

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        client = MediaRunnerHttpClient(
            base_url="http://runner",
            secret=SECRET.encode(),
            workspace_root=tmp_path,
            inspect_timeout_seconds=5,
            download_timeout_seconds=5,
            client=http,
        )
        result = await client.reconcile_inspection(URL, execution)
        assert result.access_context == context
    assert len(calls) == 2 and "/internal/inspect" not in calls
    assert len(supervisor.calls) == 1
