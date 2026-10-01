"""Failure location and thirteen categories cross the signed Runner boundary."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from app.integrations.media_runner import MediaRunnerHttpClient
from app.integrations.media_runner_models import MediaRunnerClientError
from app.services.provider_failures import (
    FailureClass,
    FailureEvidenceKind,
    FailurePhase,
)
from app.workers.runner.contracts import ProviderFailureContract, RunnerErrorContract
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.main import create_app
from tests.unit.workers.runner.api_helpers import FakeService
from tests.unit.workers.runner.helpers import SECRET, download_request, settings


@pytest.mark.parametrize("category", list(FailureClass))
async def test_signed_failure_preserves_category_layer_stage_and_summary(
    tmp_path: Path, category
):
    context = download_request().execution_context.to_domain()
    error = RunnerFailure(category.value, status=422).attributed_to(context)

    class FailingService(FakeService):
        async def inspect(self, _url, **_kwargs):
            raise error

    async with httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.ASGITransport(
            app=create_app(settings(tmp_path), service=FailingService()),
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
        with pytest.raises(MediaRunnerClientError) as caught:
            await client.inspect("https://vimeo.com/1")
    assert caught.value.failure == error.failure
    assert caught.value.failure.failure_class is category
    assert caught.value.failure.layer == "L1"
    assert caught.value.failure.stage == "resolve"
    assert caught.value.failure.summary


@pytest.mark.parametrize(
    "mutation", ["code", "layer", "stage", "failure_class", "extra"]
)
async def test_invalid_failure_facts_are_rejected(mutation):
    facts = ProviderFailureContract.from_domain(RunnerFailure("challenge").failure)
    document = RunnerErrorContract(
        code="challenge", message="rejected", failure=facts
    ).model_dump(mode="json")
    if mutation == "code":
        document["failure"]["code"] = "login_required"
    elif mutation == "failure_class":
        document["failure"][mutation] = "login_required"
    elif mutation == "extra":
        document["failure"]["unknown_field"] = True
    else:
        document["failure"][mutation] = "invalid"

    async def respond(request):
        if request.url.path == "/internal/runtime":
            return httpx.Response(200, json={"instance_id": "0" * 32})
        return httpx.Response(422, json={"error": document})

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        client = MediaRunnerHttpClient(
            base_url="http://runner",
            secret=b"s" * 32,
            workspace_root=Path("."),
            inspect_timeout_seconds=1,
            download_timeout_seconds=1,
            client=http,
        )
        with pytest.raises(MediaRunnerClientError, match="invalid_runner_response"):
            await client.inspect("https://vimeo.com/1")


def test_error_phase_change_also_updates_public_stage():
    error = RunnerFailure("transient").during(FailurePhase.TRANSFER)
    assert error.failure.stage == "download"
    assert error.during(FailurePhase.VALIDATE).failure.stage == "validate"


@pytest.mark.parametrize(
    ("internal_code", "category"),
    [
        ("inspection_failed", "extractor_broken"),
        ("inspection_timeout", "transient"),
        ("download_timeout", "transient"),
        ("media_probe_failed", "extractor_broken"),
        ("drm_protected", "content_protected"),
        ("content_preview_only", "content_protected"),
        ("source_changed", "context_changed"),
        ("engine_unavailable", "runtime_unavailable"),
    ],
)
async def test_public_media_failure_code_is_a_category(
    tmp_path, internal_code, category
):
    class FailingService(FakeService):
        async def inspect(self, _url, **_kwargs):
            raise RunnerFailure(internal_code, status=422)

    async with httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.ASGITransport(
            app=create_app(settings(tmp_path), service=FailingService()),
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
        with pytest.raises(MediaRunnerClientError) as caught:
            await client.inspect("https://vimeo.com/1")
    assert caught.value.code == category
    assert caught.value.failure.code == category
    assert caught.value.failure.failure_class.value == category


async def test_signed_429_preserves_retry_after_and_safe_evidence(tmp_path):
    retry_after = datetime.now(UTC) + timedelta(seconds=30)
    error = RunnerFailure(
        "rate_limited",
        status=429,
        retry_after=retry_after,
        evidence_kind=FailureEvidenceKind.UPSTREAM_RESPONSE,
        evidence={"kind": "upstream_response", "http_status": 429},
    )

    class LimitedService(FakeService):
        async def inspect(self, _url, **_kwargs):
            raise error

    async with httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.ASGITransport(
            app=create_app(settings(tmp_path), service=LimitedService())
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
        with pytest.raises(MediaRunnerClientError) as caught:
            await client.inspect("https://vimeo.com/1")
    assert caught.value.code == "rate_limited"
    assert caught.value.status == 429
    assert caught.value.retry_at == retry_after
    assert caught.value.failure.evidence == {
        "kind": "upstream_response",
        "http_status": 429,
    }


async def test_cleanup_ack_allows_same_task_id_recovery_through_signed_client(tmp_path):
    service = FakeService()
    async with httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.ASGITransport(
            app=create_app(settings(tmp_path), service=service)
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
        await client.cancel("parse_fixture")
        recovered = await client.inspect("https://vimeo.com/1", task_id="parse_fixture")
    assert recovered.title == "Fixture"
    assert service.cancelled == ["parse_fixture"]
    assert service.inspected_url == "https://vimeo.com/1"
