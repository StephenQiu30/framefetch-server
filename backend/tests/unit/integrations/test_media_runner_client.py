"""Exercise the signed anonymous Runner boundary and artifact path checks."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest
from app.integrations.media_runner import MediaRunnerHttpClient, _retry_after
from app.integrations.media_runner_models import MediaRunnerClientError
from app.services.downloads.errors import MediaInspectionFailure
from app.services.provider_types import ExecutionContext
from app.workers.runner.contracts import ProviderFailureContract, RunnerErrorContract
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.signing import sign_request
from tests.unit.workers.runner.helpers import download_request

SECRET = b"s" * 32
INSTANCE = "0" * 32


def client(http: httpx.AsyncClient, root: Path) -> MediaRunnerHttpClient:
    return MediaRunnerHttpClient(
        base_url="http://runner",
        secret=SECRET,
        workspace_root=root,
        inspect_timeout_seconds=1,
        download_timeout_seconds=1,
        client=http,
        clock=lambda: 1000,
        nonce=lambda: "fixture_nonce_1234567890",
    )


def context() -> ExecutionContext:
    return download_request().execution_context.to_domain()


def inspection() -> dict[str, object]:
    return {
        "media": {
            "provider_media_id": "controlled",
            "title": "Controlled",
            "duration_seconds": 30,
            "extractor_key": "Controlled",
        },
        "streams": [],
        "options": [],
        "execution_context": context().to_document(),
    }


def test_retry_after_parses_seconds_dates_and_rejects_malformed_values():
    before = datetime.now(UTC)
    numeric = _retry_after("600")
    assert numeric is not None and 600 <= (numeric - before).total_seconds() < 601
    assert _retry_after(format_datetime(numeric)) is not None
    for invalid in ("-1", "NaN", "infinity", "9" * 200, "tomorrow", None):
        assert _retry_after(invalid) is None


async def test_inspect_has_cancellation_resource_and_execution_context_and_is_signed(
    tmp_path,
):
    captured = []

    async def respond(request):
        captured.append(request)
        if request.url.path == "/internal/runtime":
            return httpx.Response(200, json={"instance_id": INSTANCE})
        assert request.url.path == "/internal/inspect"
        sent = json.loads(request.content)
        assert sent["task_id"] == "parse_fixture"
        assert sent["url"] == "https://media.example.com/video"
        assert sent["execution_context"] is None
        assert datetime.fromisoformat(sent["deadline"]).tzinfo is not None
        assert datetime.fromisoformat(sent["issued_at"]).timestamp() >= 1000
        assert request.headers["X-Runner-Instance"] == INSTANCE
        assert request.headers["X-Runner-Signature"] == sign_request(
            SECRET,
            "POST",
            "/internal/inspect",
            request.content,
            1000,
            "fixture_nonce_1234567890",
            runtime_instance_id=INSTANCE,
        )
        return httpx.Response(200, json=inspection())

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        result = await client(http, tmp_path).inspect(
            "https://media.example.com/video", task_id="parse_fixture"
        )
    assert result.execution_context == context()
    assert len(captured) == 2


@pytest.mark.parametrize("broken", [None, {}, {"media": {}}])
async def test_invalid_runner_response_is_rejected(tmp_path, broken):
    async def respond(request):
        if request.url.path == "/internal/runtime":
            return httpx.Response(200, json={"instance_id": INSTANCE})
        return httpx.Response(200, json=broken)

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        with pytest.raises(MediaInspectionFailure, match="invalid_runner_response"):
            await client(http, tmp_path).inspect("https://media.example.com/video")


@pytest.mark.parametrize(
    "failure_type, expected",
    [
        (httpx.ReadTimeout, "transient"),
        (httpx.ConnectError, "runner_unavailable"),
    ],
)
async def test_transport_failures_keep_bounded_stable_codes(
    tmp_path, failure_type, expected
):
    async def respond(request):
        if request.url.path == "/internal/runtime":
            return httpx.Response(200, json={"instance_id": INSTANCE})
        raise failure_type("private upstream message", request=request)

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        with pytest.raises(MediaInspectionFailure) as caught:
            await client(http, tmp_path).inspect("https://media.example.com/video")
    assert str(caught.value) == expected
    assert "private" not in str(caught.value)


async def test_failure_facts_and_retry_after_survive_http_projection(tmp_path):
    error = RunnerFailure("rate_limited", status=429)
    document = RunnerErrorContract(
        code=error.code,
        message=error.message,
        failure=ProviderFailureContract.from_domain(error.failure),
    ).model_dump(mode="json")

    async def respond(request):
        if request.url.path == "/internal/runtime":
            return httpx.Response(200, json={"instance_id": INSTANCE})
        return httpx.Response(
            429, json={"error": document}, headers={"Retry-After": "30"}
        )

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        with pytest.raises(MediaInspectionFailure) as caught:
            await client(http, tmp_path).inspect("https://media.example.com/video")
    assert caught.value.failure.layer == "L1"
    assert caught.value.failure.stage == "resolve"
    assert caught.value.failure.retry_after is not None


@pytest.mark.parametrize(
    "workspace, relative_path, valid",
    [
        ("inside", "artifact.mp4", True),
        ("outside", "artifact.mp4", False),
        ("inside", "../../outside.mp4", False),
        ("inside", "/outside.mp4", False),
    ],
)
async def test_download_rejects_artifact_outside_shared_workspace(
    tmp_path, workspace, relative_path, valid
):
    request = download_request()
    root = tmp_path / "root"
    selected = root / "job" if workspace == "inside" else tmp_path / "outside"

    async def respond(http_request):
        if http_request.url.path == "/internal/runtime":
            return httpx.Response(200, json={"instance_id": INSTANCE})
        assert (
            json.loads(http_request.content)["execution_context"]
            == context().to_document()
        )
        assert json.loads(http_request.content)["expected_duration_seconds"] == 30
        assert http_request.headers["X-Runner-Signature"] == sign_request(
            SECRET,
            "POST",
            "/internal/download",
            http_request.content,
            1000,
            "fixture_nonce_1234567890",
            runtime_instance_id=INSTANCE,
        )
        return httpx.Response(
            200,
            json={
                "task_id": request.task_id,
                "workspace_path": str(selected),
                "artifact": {
                    "relative_path": relative_path,
                    "size_bytes": 5,
                    "sha256": "a" * 64,
                    "duration_seconds": 30,
                    "container": "mp4",
                    "video_streams": 1,
                    "audio_streams": 1,
                },
            },
        )

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        operation = client(http, root).download(
            request.task_id,
            request.url,
            request.plan.to_domain(),
            expected_provider_media_id=request.expected_provider_media_id,
            expected_extractor_key=request.expected_extractor_key,
            expected_duration_seconds=request.expected_duration_seconds,
            execution_context=context(),
        )
        if valid:
            result = await operation
            assert result.sha256 == "a" * 64 and result.size_bytes == 5
        else:
            with pytest.raises(MediaRunnerClientError, match="invalid_artifact_path"):
                await operation


async def test_inspection_cancellation_waits_for_pinned_cleanup_ack_and_retries_loss(
    tmp_path,
):
    started, cleaning, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
    cancel_requests = []

    async def respond(request):
        if request.url.path == "/internal/runtime":
            return httpx.Response(200, json={"instance_id": INSTANCE})
        if request.url.path == "/internal/inspect":
            started.set()
            await asyncio.Event().wait()
        cancel_requests.append(request)
        assert request.url.path == "/internal/tasks/parse_fixture/cancel"
        assert request.headers["X-Runner-Instance"] == INSTANCE
        cleaning.set()
        await finish.wait()
        if len(cancel_requests) == 1:
            raise httpx.ReadTimeout("lost reply", request=request)
        return httpx.Response(
            200,
            json={
                "task_id": "parse_fixture",
                "status": "stopped",
                "cleanup_token": "a" * 32,
            },
        )

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        task = asyncio.create_task(
            client(http, tmp_path).inspect(
                "https://vimeo.com/1", task_id="parse_fixture"
            )
        )
        await started.wait()
        task.cancel()
        await cleaning.wait()
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
    assert len(cancel_requests) == 2


async def test_inspection_cancel_without_ack_surfaces_failure(tmp_path):
    started = asyncio.Event()
    attempts = 0

    async def respond(request):
        nonlocal attempts
        if request.url.path == "/internal/runtime":
            return httpx.Response(200, json={"instance_id": INSTANCE})
        if request.url.path == "/internal/inspect":
            started.set()
            await asyncio.Event().wait()
        attempts += 1
        raise httpx.ReadTimeout("lost reply", request=request)

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        task = asyncio.create_task(
            client(http, tmp_path).inspect(
                "https://vimeo.com/1", task_id="parse_fixture"
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(MediaInspectionFailure, match="runtime_unavailable"):
            await asyncio.wait_for(task, 1)
    assert attempts == 3


async def test_cancel_confirms_old_resource_is_lost_only_after_boot_change(tmp_path):
    started = asyncio.Event()
    runtime_calls = 0
    cancelled_instances = []

    async def respond(request):
        nonlocal runtime_calls
        if request.url.path == "/internal/runtime":
            runtime_calls += 1
            return httpx.Response(
                200, json={"instance_id": INSTANCE if runtime_calls == 1 else "1" * 32}
            )
        if request.url.path == "/internal/inspect":
            started.set()
            await asyncio.Event().wait()
        cancelled_instances.append(request.headers["X-Runner-Instance"])
        error = RunnerFailure("runner_restarted", status=409)
        return httpx.Response(
            409,
            json={
                "error": RunnerErrorContract(
                    code=error.code,
                    message=error.message,
                    failure=ProviderFailureContract.from_domain(error.failure),
                ).model_dump(mode="json")
            },
        )

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        task = asyncio.create_task(
            client(http, tmp_path).inspect(
                "https://vimeo.com/1", task_id="parse_fixture"
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
    assert runtime_calls == 2
    assert cancelled_instances == [INSTANCE]


@pytest.mark.parametrize(
    "ack",
    [
        {"task_id": "different", "status": "stopped"},
        {"task_id": "parse_fixture", "status": "running"},
    ],
)
async def test_cancel_rejects_mismatched_or_incomplete_ack(tmp_path, ack):
    async def respond(request):
        if request.url.path == "/internal/runtime":
            return httpx.Response(200, json={"instance_id": INSTANCE})
        return httpx.Response(200, json=ack)

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        with pytest.raises(MediaRunnerClientError, match="invalid_runner_response"):
            await client(http, tmp_path).cancel("parse_fixture")


async def test_download_validation_failure_retains_business_error_after_projection(
    tmp_path,
):
    from app.services.download_execution.errors import classify_runner_failure
    from app.services.downloads.rules.enums import DownloadErrorCode
    from app.workers.runner.main import create_app
    from tests.unit.workers.runner.api_helpers import FakeService
    from tests.unit.workers.runner.helpers import settings

    config = settings(tmp_path)

    class FailingService(FakeService):
        async def download(self, _request):
            raise RunnerFailure("invalid_artifact")

    async with httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.ASGITransport(app=create_app(config, service=FailingService())),
    ) as http:
        runner = MediaRunnerHttpClient(
            base_url="http://runner",
            secret=config.runner_hmac_secret.get_secret_value().encode(),
            workspace_root=tmp_path,
            inspect_timeout_seconds=5,
            download_timeout_seconds=5,
            client=http,
        )
        with pytest.raises(MediaRunnerClientError) as caught:
            await runner.download(
                "job_fixture",
                "https://media.example.com/video",
                download_request().plan.to_domain(),
                expected_provider_media_id="controlled",
                expected_extractor_key="Controlled",
                expected_duration_seconds=30,
                execution_context=context(),
            )
    assert caught.value.code == "extractor_broken"
    assert caught.value.failure.stage == "validate"
    assert (
        classify_runner_failure(caught.value)
        is DownloadErrorCode.MEDIA_VALIDATION_FAILED
    )
