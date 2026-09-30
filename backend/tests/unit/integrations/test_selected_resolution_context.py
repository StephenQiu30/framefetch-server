"""The wire preparation must retain the selected route, including same-mode routes."""

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from app.integrations.media_runner import MediaRunnerHttpClient
from app.services.downloads.errors import (
    MediaInspectionFailure,
    MediaInspectionTemporarilyUnavailable,
)
from app.services.downloads.resolution import ResolutionPlan
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_failures import FailureClass, FailurePhase, FailureScope
from tests.resolution import capability_for, preparation_for

URL = "https://media.example/video"


@pytest.mark.parametrize("returned", ["selected", "primary", "wrong_adapter"])
async def test_selected_same_mode_route_and_revision_survive_http_preparation(
    returned,
):
    primary = capability_for(
        ProviderAccessPolicy.PUBLIC, provider_key="generic", version="default"
    )
    selected = replace(
        primary.strategies[0], strategy_id="http-backup", adapter_revision="adapter-b"
    )
    capability = replace(primary, strategies=(*primary.strategies, selected))
    plan = ResolutionPlan(capability, 0)
    expected = preparation_for(plan, selected.strategy_id).context
    captured = []

    async def respond(request):
        captured.append(request.url.path)
        if request.url.path == "/internal/context":
            assert json.loads(request.content) == {
                "url": URL,
                "access_mode": "anonymous",
                "strategy_id": selected.strategy_id,
                "plan_revision": plan.revision,
            }
            context = (
                preparation_for(plan, primary.strategies[0].strategy_id).context
                if returned == "primary"
                else expected
            )
            if returned == "wrong_adapter":
                context = replace(context, adapter_revision="unexpected-revision")
            return httpx.Response(200, json=context.to_document())
        assert request.url.path == "/internal/runtime"
        return httpx.Response(200, json={"instance_id": "c" * 32})

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        runner = MediaRunnerHttpClient(
            base_url="http://runner",
            secret=b"s" * 32,
            workspace_root=Path("."),
            inspect_timeout_seconds=1,
            download_timeout_seconds=1,
            client=http,
        )
        if returned != "selected":
            with pytest.raises(MediaInspectionFailure) as failure:
                await runner.prepare_resolution(URL, plan, selected.strategy_id)
            assert failure.value.failure.code == (
                "client_context_mismatch"
                if returned == "primary"
                else "context_changed"
            )
            assert captured == ["/internal/context"]
        else:
            prepared = await runner.prepare_resolution(URL, plan, selected.strategy_id)
            assert prepared.context == expected
            assert prepared.runner_instance_id == "c" * 32
            assert captured == ["/internal/context", "/internal/runtime"]


@pytest.mark.parametrize(
    "code",
    [
        "credential_access_denied",
        "source_read_timeout",
        "source_read_failed",
        "chrome_profile_unavailable",
    ],
)
async def test_source_preparation_failure_keeps_the_root_reason_in_business(code):
    plan = ResolutionPlan(
        capability_for(ProviderAccessPolicy.PUBLIC, provider_key="generic"), 0
    )
    requested = []

    async def respond(request):
        requested.append(request.url.path)
        return httpx.Response(503, json={"error": {"code": code}})

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        runner = MediaRunnerHttpClient(
            base_url="http://runner",
            secret=b"s" * 32,
            workspace_root=Path("."),
            inspect_timeout_seconds=1,
            download_timeout_seconds=1,
            client=http,
        )
        with pytest.raises(MediaInspectionTemporarilyUnavailable) as caught:
            await runner.prepare_resolution(URL, plan, plan.first_strategy.strategy_id)
    failure = caught.value.failure
    assert failure.code == code
    assert failure.phase is FailurePhase.PREPARE_CONTEXT
    assert failure.scope is FailureScope.SESSION
    assert failure.failure_class is FailureClass.RUNTIME_UNAVAILABLE
    assert requested == ["/internal/context"]
