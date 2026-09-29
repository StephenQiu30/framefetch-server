import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from app.core.db import create_session_factory
from app.integrations.media_runner import MediaRunnerHttpClient
from app.repositories.providers.route_cooldowns import SqlAlchemyProviderRouteCooldowns
from app.services.downloads.errors import (
    MediaInspectionRateLimited,
    MediaInspectionVerificationFailed,
)
from app.services.provider_route_admission import ProviderRouteAdmission
from app.services.provider_types import ProviderAccessMode
from tests.unit.integrations.test_media_runner_client import _access_context
from tests.unit.services.test_provider_route_admission import Cooldowns


async def test_independent_api_and_canary_clients_share_durable_429_gate(
    postgres_engine,
):
    calls = []

    async def respond(request):
        if request.url.path == "/internal/runtime":
            return httpx.Response(200, json={"instance_id": "0" * 32})
        calls.append(request.url.path)
        if request.url.path == "/internal/context":
            return httpx.Response(200, json=_access_context().to_document())
        assert request.url.path == "/internal/inspect"
        return httpx.Response(429, json={"error": {"code": "provider_rate_limited"}})

    sessions = create_session_factory(postgres_engine)
    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        for _ in range(2):
            client = MediaRunnerHttpClient(
                base_url="http://runner",
                secret=b"s" * 32,
                workspace_root=Path("."),
                inspect_timeout_seconds=2,
                download_timeout_seconds=2,
                client=http,
                admission=ProviderRouteAdmission(
                    SqlAlchemyProviderRouteCooldowns(sessions)
                ),
            )
            with pytest.raises(MediaInspectionRateLimited) as result:
                await client.inspect("https://media.example/owned")
            assert result.value.retry_at is not None
    assert calls.count("/internal/inspect") == 1
    assert calls.count("/internal/context") == 2  # Local non-media context only.


async def test_wrong_runner_role_is_rejected_before_any_platform_request():
    calls = []
    wrong = replace(
        _access_context(),
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
        credential_version_id="controlled",
    )

    async def respond(request):
        if request.url.path == "/internal/runtime":
            return httpx.Response(200, json={"instance_id": "0" * 32})
        calls.append(request.url.path)
        assert request.url.path == "/internal/context"
        return httpx.Response(200, json=wrong.to_document())

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        client = MediaRunnerHttpClient(
            base_url="http://runner",
            secret=b"s" * 32,
            workspace_root=Path("."),
            inspect_timeout_seconds=2,
            download_timeout_seconds=2,
            client=http,
            expected_access_mode=ProviderAccessMode.ANONYMOUS,
        )
        with pytest.raises(MediaInspectionVerificationFailed):
            await client.inspect("https://media.example/owned")
    assert calls == ["/internal/context"]


async def test_half_open_client_transmits_context_and_deadline_before_platform_io():
    async def respond(request):
        if request.url.path == "/internal/runtime":
            return httpx.Response(200, json={"instance_id": "0" * 32})
        if request.url.path == "/internal/context":
            return httpx.Response(200, json=_access_context().to_document())
        payload = json.loads(request.content)
        assert payload["access_context"] == _access_context().to_document()
        assert datetime.fromisoformat(payload["deadline_at"]).tzinfo is not None
        return httpx.Response(429, json={"error": {"code": "provider_rate_limited"}})

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        client = MediaRunnerHttpClient(
            base_url="http://runner",
            secret=b"s" * 32,
            workspace_root=Path("."),
            inspect_timeout_seconds=2,
            download_timeout_seconds=2,
            client=http,
            admission=ProviderRouteAdmission(Cooldowns(half_open=True)),
        )
        with pytest.raises(MediaInspectionRateLimited):
            await client.inspect("https://media.example/owned")
