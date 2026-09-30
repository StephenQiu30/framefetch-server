"""Exercise failure facts through signed Runner HTTP and the business boundary."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from app.integrations.media_runner import MediaRunnerHttpClient
from app.integrations.media_runner_models import MediaRunnerClientError
from app.services.downloads.errors import ApplicationError, ApplicationErrorCode
from app.services.provider_failures import FailureEvidenceKind, FailurePhase
from app.workers.runner.contracts import ProviderFailureContract, RunnerErrorContract
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.main import create_app
from tests.unit.services.test_inspect_media import (
    OWNER,
    URL,
    FakeRepository,
    runner_result,
    use_case,
)
from tests.unit.workers.runner.api_helpers import FakeService
from tests.unit.workers.runner.helpers import SECRET, download_request, settings


@pytest.mark.parametrize(
    "code,phase",
    [
        ("credential_required", FailurePhase.FETCH_METADATA),
        ("credential_expired", FailurePhase.FETCH_METADATA),
        ("egress_challenged", FailurePhase.FETCH_METADATA),
        ("pot_required", FailurePhase.PREPARE_CONTEXT),
        ("pot_rejected", FailurePhase.FETCH_METADATA),
        ("pot_provider_unavailable", FailurePhase.PREPARE_CONTEXT),
        ("extractor_regression", FailurePhase.FETCH_METADATA),
        ("network_transient", FailurePhase.PROBE_MEDIA),
        ("media_probe_failed", FailurePhase.PROBE_MEDIA),
        ("provider_rate_limited", FailurePhase.TRANSFER),
        ("content_private", FailurePhase.FETCH_METADATA),
        ("upstream_unclassified", FailurePhase.FETCH_METADATA),
        ("client_context_mismatch", FailurePhase.PREPARE_CONTEXT),
        ("invalid_artifact", FailurePhase.VALIDATE),
        ("storage_unavailable", FailurePhase.PUBLISH),
    ],
)
async def test_signed_failure_reaches_business_without_losing_facts(
    tmp_path: Path,
    code: str,
    phase: FailurePhase,
) -> None:
    context = download_request().access_context.to_domain()
    error = RunnerFailure(
        code,
        status=422,
        phase=phase,
        evidence_kind=FailureEvidenceKind.UPSTREAM_RESPONSE,
        retry_after=datetime.now(UTC) + timedelta(seconds=60)
        if code == "provider_rate_limited"
        else None,
    )
    error.attributed_to(context)

    class FailingService(FakeService):
        async def inspect(self, _url, **_kwargs):
            raise error

    async with httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.ASGITransport(
            app=create_app(settings(tmp_path), service=FailingService())
        ),
    ) as http:
        client = MediaRunnerHttpClient(
            base_url="http://runner",
            secret=SECRET.encode(),
            workspace_root=tmp_path,
            inspect_timeout_seconds=5,
            download_timeout_seconds=5,
            client=http,
        )
        inspector, runner, _ = use_case(FakeRepository(), runner_result())

        async def inspect(url, **_kwargs):
            return await client.inspect(url)

        runner.inspect = AsyncMock(side_effect=inspect)
        with pytest.raises(ApplicationError) as caught:
            await inspector.prepare(URL, OWNER, "failure-contract")
    assert caught.value.failure == error.failure
    assert caught.value.failure.code == code
    assert caught.value.failure.phase is phase
    assert caught.value.failure.context_key == context.generation_id
    if code in {
        "pot_required",
        "pot_rejected",
        "client_context_mismatch",
        "network_transient",
        "upstream_unclassified",
        "media_probe_failed",
    }:
        assert caught.value.code not in {
            ApplicationErrorCode.PROVIDER_AUTH_REQUIRED,
            ApplicationErrorCode.PROVIDER_SESSION_EXPIRED,
            ApplicationErrorCode.PROVIDER_VERIFICATION_FAILED,
        }
    if code == "provider_rate_limited":
        assert caught.value.retry_at == error.failure.retry_after


@pytest.mark.parametrize(
    "mutation", ["code", "phase", "scope", "context_key", "failure_class", "extra"]
)
async def test_invalid_failure_facts_are_rejected(mutation: str) -> None:
    facts = ProviderFailureContract.from_domain(RunnerFailure("pot_rejected").failure)
    document = RunnerErrorContract(
        code="pot_rejected", message="rejected", failure=facts
    ).model_dump(mode="json")
    if mutation == "code":
        document["failure"]["code"] = "credential_required"
    elif mutation == "failure_class":
        document["failure"][mutation] = "auth_required"
    elif mutation == "scope":
        document["failure"][mutation] = "session"
    elif mutation == "extra":
        document["failure"]["unrecognized_field"] = True
    else:
        document["failure"][mutation] = "invalid"

    async def response(_request):
        return httpx.Response(422, json={"error": document})

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(response)
    ) as http:
        client = MediaRunnerHttpClient(
            base_url="http://runner",
            secret=b"s" * 32,
            workspace_root=Path("."),
            inspect_timeout_seconds=1,
            download_timeout_seconds=1,
            client=http,
        )
        with pytest.raises(MediaRunnerClientError) as caught:
            await client.context("https://vimeo.com/1")
    assert caught.value.code == "invalid_runner_response"
