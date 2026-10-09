from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from api_helpers import (
    FakeService,
    anonymous_access_context,
    inspect_document,
    settings,
    signed_headers,
)
from app.workers.runner.main import create_app
from fastapi.testclient import TestClient


class Readiness:
    def __init__(self, available: bool) -> None:
        self.available = available

    async def check(self) -> bool:
        return self.available


def test_internal_media_contract_has_only_direct_operation_paths(tmp_path):
    app = create_app(settings(tmp_path), service=FakeService())
    assert {
        path for path in app.openapi()["paths"] if path.startswith("/internal/")
    } == {
        "/internal/engine-catalog",
        "/internal/runtime",
        "/internal/inspect",
        "/internal/download",
        "/internal/tasks/{task_id}",
        "/internal/tasks/{task_id}/cancel",
    }


def test_manual_platform_login_endpoint_is_removed(tmp_path):
    client = TestClient(create_app(settings(tmp_path), service=FakeService()))
    assert client.post("/internal/site-sessions/login", json={}).status_code == 404


def test_health_is_public_and_inspect_requires_valid_raw_body_signature(
    tmp_path: Path,
) -> None:
    service = FakeService()
    client = TestClient(create_app(settings(tmp_path), service=service))
    body = json.dumps(inspect_document("https://media.example.com/video")).encode()
    path = "/internal/inspect"
    headers = signed_headers(path, body, "inspect_nonce_123456")

    assert client.get("/health/live").json() == {
        "service": "media-runner",
        "status": "live",
    }
    response = client.post(path, content=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["media"]["title"] == "Fixture"
    assert response.json()["media"]["provider_media_id"] == "fixture-id"
    assert response.json()["media"]["extractor_key"] == "Controlled"
    assert service.inspected_url == "https://media.example.com/video"

    replay = client.post(path, content=body, headers=headers)
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "request_replayed"


def test_readiness_fails_closed_until_runner_dependencies_are_ready(
    tmp_path: Path,
) -> None:
    unavailable = TestClient(
        create_app(
            settings(tmp_path),
            service=FakeService(),
            readiness=Readiness(False),
        )
    )
    available = TestClient(
        create_app(
            settings(tmp_path),
            service=FakeService(),
            readiness=Readiness(True),
        )
    )

    assert unavailable.get("/health/ready").status_code == 503
    assert unavailable.get("/health/live").status_code == 200
    assert available.get("/health/ready").json() == {
        "service": "media-runner",
        "status": "ready",
    }


@pytest.mark.parametrize(
    ("path", "payload"),
    (
        ("/internal/inspect", {"url": "https://media.example.com/video"}),
        (
            "/internal/download",
            {
                "task_id": "job_123",
                "issued_at": datetime.now(UTC).isoformat(),
                "url": "https://media.example.com/video",
                "expected_provider_media_id": "controlled",
                "expected_extractor_key": "Controlled",
                "expected_duration_seconds": 30,
                "execution_context": anonymous_access_context(),
                "plan": {
                    "height": 1080,
                    "width": 1920,
                    "fps_bucket": "fps_30",
                    "dynamic_range": "sdr",
                    "video_codec_family": "h264",
                    "audio_codec_family": "aac",
                    "audio_language": "zh-CN",
                    "container_preference": "mp4",
                    "compatibility_profile": "balanced",
                    "hints": {"video_id": "v", "audio_id": "a"},
                },
            },
        ),
    ),
)
def test_signed_work_is_rejected_when_installed_engine_does_not_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict[str, object],
) -> None:
    monkeypatch.setattr(
        "app.workers.runner.main._runtime_packages_ready", lambda _settings: False
    )
    service = FakeService()
    client = TestClient(create_app(settings(tmp_path), service=service))
    body = json.dumps(
        inspect_document(**payload) if path == "/internal/inspect" else payload
    ).encode()

    response = client.post(
        path,
        content=body,
        headers=signed_headers(path, body, "engine_drift_nonce_12345"),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "runtime_unavailable"
    assert service.inspected_url is None
    assert service.download_request is None


def test_tampered_or_unsigned_request_has_stable_error(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path), service=FakeService()))
    path = "/internal/inspect"
    original = b'{"url":"https://media.example.com/video"}'
    headers = signed_headers(path, original, "tampered_nonce_12345")

    tampered = client.post(
        path,
        content=b'{"url":"https://evil.example/x"}',
        headers=headers,
    )
    unsigned = client.post(path, content=original)

    assert tampered.status_code == 401
    assert tampered.json()["error"]["code"] == "invalid_signature"
    assert unsigned.status_code == 401
    assert unsigned.json()["error"]["code"] == "authentication_required"

    query = client.post(f"{path}?unsigned=1", content=original, headers=headers)
    assert query.status_code == 422
    assert query.json()["error"]["code"] == "invalid_request"


def test_download_uses_signed_stable_contract(tmp_path: Path) -> None:
    service = FakeService()
    client = TestClient(create_app(settings(tmp_path), service=service))
    path = "/internal/download"
    payload = {
        "task_id": "job_123",
        "issued_at": datetime.now(UTC).isoformat(),
        "url": "https://media.example.com/video",
        "expected_provider_media_id": "controlled",
        "expected_extractor_key": "Controlled",
        "expected_duration_seconds": 30,
        "execution_context": anonymous_access_context(),
        "plan": {
            "height": 1080,
            "width": 1920,
            "fps_bucket": "fps_30",
            "dynamic_range": "sdr",
            "video_codec_family": "h264",
            "audio_codec_family": "aac",
            "audio_language": "zh-CN",
            "container_preference": "mp4",
            "compatibility_profile": "balanced",
            "hints": {"video_id": "v", "audio_id": "a"},
        },
    }
    body = json.dumps(payload).encode()

    response = client.post(
        path,
        content=body,
        headers=signed_headers(path, body, "download_nonce_12345"),
    )

    assert response.status_code == 200
    assert response.json()["artifact"]["sha256"] == "a" * 64
    assert service.download_request is not None
    assert service.download_request.plan.height == 1080


def test_download_rejects_invalid_semantic_plan_before_service(tmp_path: Path) -> None:
    service = FakeService()
    client = TestClient(create_app(settings(tmp_path), service=service))
    path = "/internal/download"
    body = json.dumps(
        {
            "task_id": "job_123",
            "issued_at": datetime.now(UTC).isoformat(),
            "url": "https://media.example.com/video",
            "expected_provider_media_id": "controlled",
            "expected_extractor_key": "Controlled",
            "expected_duration_seconds": 30,
            "execution_context": anonymous_access_context(),
            "plan": {
                "height": -1,
                "width": 1920,
                "fps_bucket": "fps_30",
                "dynamic_range": "sdr",
                "video_codec_family": "h264",
                "audio_codec_family": "aac",
                "container_preference": "mp4",
                "compatibility_profile": "balanced",
            },
        }
    ).encode()

    response = client.post(
        path,
        content=body,
        headers=signed_headers(path, body, "invalid_plan_nonce_12"),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert service.download_request is None


def test_execution_binding_rejects_old_boot_and_tampered_header(tmp_path, monkeypatch):
    from uuid import UUID

    service = FakeService()
    monkeypatch.setattr("app.workers.runner.main.uuid4", lambda: UUID(int=1))
    client = TestClient(create_app(settings(tmp_path), service=service))
    path = "/internal/inspect"
    body = b'{"url":"https://media.example.com/video"}'
    # Helper signs for boot zero; a new process has lost nonce memory but must
    # still reject this delayed, otherwise valid execution from the old boot.
    headers = signed_headers(path, body, "old_boot_nonce_123456")
    response = client.post(path, content=body, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "runner_restarted"
    assert service.inspected_url is None

    headers = signed_headers(path, body, "tamper_boot_nonce_123456")
    headers["X-Runner-Instance"] = UUID(int=1).hex
    response = client.post(path, content=body, headers=headers)
    assert response.status_code == 401
    assert service.inspected_url is None

    runtime_path = "/internal/runtime"
    response = client.get(
        runtime_path,
        headers=signed_headers(runtime_path, b"", "runtime_nonce_123456", method="GET"),
    )
    assert response.json() == {"instance_id": UUID(int=1).hex}
    assert client.get(runtime_path).status_code == 401


@pytest.mark.parametrize(
    "field", ["strategy_id", "plan_revision", "operation_id", "deadline_at"]
)
def test_inspect_rejects_deleted_control_fields(tmp_path, field):
    client = TestClient(create_app(settings(tmp_path), service=FakeService()))
    path = "/internal/inspect"
    body = json.dumps(
        inspect_document("https://media.example.com/video", **{field: "obsolete"})
    ).encode()
    response = client.post(
        path, content=body, headers=signed_headers(path, body, "controls_nonce_12345")
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_inspection_returns_only_the_twelve_execution_context_fields(tmp_path):
    client = TestClient(create_app(settings(tmp_path), service=FakeService()))
    path = "/internal/inspect"
    body = json.dumps(inspect_document("https://media.example.com/video")).encode()
    response = client.post(
        path,
        content=body,
        headers=signed_headers(path, body, "context_fields_nonce_123"),
    )
    assert response.status_code == 200
    assert set(response.json()["execution_context"]) == {
        "provider_key",
        "resolved_layer",
        "egress_route",
        "client",
        "registry_revision",
        "egress_revision",
        "egress_class",
        "egress_observed_ip",
        "identity_digest",
        "browser_context_kind",
        "identity_used",
        "engine_revision",
    }


def test_cancel_is_bound_to_the_runner_instance(tmp_path, monkeypatch):
    from uuid import UUID

    monkeypatch.setattr("app.workers.runner.main.uuid4", lambda: UUID(int=1))
    service = FakeService()
    client = TestClient(create_app(settings(tmp_path), service=service))
    path, body = "/internal/tasks/parse_fixture/cancel", b"{}"
    stale = client.post(
        path, content=body, headers=signed_headers(path, body, "cancel_old_nonce_123")
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "runner_restarted"
    assert service.cancelled == []
    current = client.post(
        path,
        content=body,
        headers=signed_headers(
            path, body, "cancel_new_nonce_123", instance_id=UUID(int=1).hex
        ),
    )
    assert current.status_code == 200
    assert current.json()["task_id"] == "parse_fixture"
    assert current.json()["status"] == "stopped"
    assert len(current.json()["cleanup_token"]) == 32
    assert service.cancelled == ["parse_fixture"]


@pytest.mark.parametrize("skew", [0, 0.7])
def test_cancel_barrier_rejects_old_request_and_allows_same_second_recovery(
    tmp_path, monkeypatch, skew
):
    now = datetime.now(UTC).replace(microsecond=100000)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr("app.workers.runner.main.datetime", Clock)
    monkeypatch.setattr("app.workers.runner.main.time.time", lambda: now.timestamp())
    service = FakeService()
    client = TestClient(create_app(settings(tmp_path), service=service))
    path = "/internal/inspect"
    old = json.dumps(
        inspect_document(
            "https://media.example.com/video",
            issued_at=(now + timedelta(seconds=skew)).isoformat(),
            deadline=(now + timedelta(seconds=120)).isoformat(),
        )
    ).encode()
    old_headers = signed_headers(path, old, "before_cancel_nonce_123")
    now = now.replace(microsecond=200000)
    cancel_path = "/internal/tasks/parse_fixture/cancel"
    ack = client.post(
        cancel_path,
        content=b"{}",
        headers=signed_headers(cancel_path, b"{}", "cancel_barrier_nonce_123"),
    )
    assert ack.status_code == 200
    response = client.post(path, content=old, headers=old_headers)
    assert response.status_code == 409
    assert service.inspected_url is None
    now = now.replace(microsecond=300000)
    fresh = json.dumps(
        inspect_document(
            "https://media.example.com/video",
            issued_at=now.isoformat(),
            deadline=(now + timedelta(seconds=120)).isoformat(),
            cleanup_token=ack.json()["cleanup_token"],
        )
    ).encode()
    response = client.post(
        path,
        content=fresh,
        headers=signed_headers(path, fresh, "after_cancel_nonce_123"),
    )
    assert response.status_code == 200
    assert (
        old_headers["X-Runner-Timestamp"]
        == signed_headers(path, fresh, "another_nonce_123")["X-Runner-Timestamp"]
    )
    assert service.inspected_url == "https://media.example.com/video"


def test_deadline_rejects_signed_request_before_runner_entry(tmp_path):
    service = FakeService()
    client = TestClient(create_app(settings(tmp_path), service=service))
    path = "/internal/inspect"
    body = json.dumps(
        inspect_document(
            "https://media.example.com/video", deadline=datetime.now(UTC).isoformat()
        )
    ).encode()
    response = client.post(
        path,
        content=body,
        headers=signed_headers(path, body, "expired_deadline_nonce_123"),
    )
    assert response.status_code == 504
    assert service.inspected_url is None


async def test_cancel_waiting_for_cleanup_rejects_new_admission(tmp_path):
    import asyncio

    import httpx

    entered, release = asyncio.Event(), asyncio.Event()

    class CleaningService(FakeService):
        async def cancel(self, task_id):
            entered.set()
            await release.wait()
            return await super().cancel(task_id)

    service = CleaningService()
    async with httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.ASGITransport(
            app=create_app(settings(tmp_path), service=service)
        ),
    ) as http:
        cancel_path = "/internal/tasks/parse_fixture/cancel"
        cancel = asyncio.create_task(
            http.post(
                cancel_path,
                content=b"{}",
                headers=signed_headers(cancel_path, b"{}", "pending_cancel_nonce_123"),
            )
        )
        await entered.wait()
        path = "/internal/inspect"
        body = json.dumps(inspect_document("https://media.example.com/video")).encode()
        response = await http.post(
            path,
            content=body,
            headers=signed_headers(path, body, "during_cleanup_nonce_123"),
        )
        assert response.status_code == 409
        assert service.inspected_url is None
        release.set()
        assert (await cancel).status_code == 200


async def test_cancel_after_handler_validation_before_work_start_rejects_late_work(
    tmp_path, monkeypatch
):
    import asyncio

    import httpx

    admitted, release = asyncio.Event(), asyncio.Event()

    async def postpone(_request, operation):
        admitted.set()
        await release.wait()
        return await operation

    monkeypatch.setattr("app.workers.runner.main._until_disconnect", postpone)
    service = FakeService()
    async with httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.ASGITransport(
            app=create_app(settings(tmp_path), service=service)
        ),
    ) as http:
        path = "/internal/inspect"
        body = json.dumps(inspect_document("https://media.example.com/video")).encode()
        pending = asyncio.create_task(
            http.post(
                path,
                content=body,
                headers=signed_headers(path, body, "delayed_entry_nonce_123"),
            )
        )
        await admitted.wait()
        cancel_path = "/internal/tasks/parse_fixture/cancel"
        ack = await http.post(
            cancel_path,
            content=b"{}",
            headers=signed_headers(cancel_path, b"{}", "before_entry_cancel_nonce_123"),
        )
        assert ack.status_code == 200
        release.set()
        assert (await pending).status_code == 409
        assert service.inspected_url is None


async def test_concurrent_cleanup_acks_keep_admission_blocked_until_both_complete(
    tmp_path,
):
    import asyncio

    import httpx

    entered = [asyncio.Event(), asyncio.Event()]
    released = [asyncio.Event(), asyncio.Event()]

    class ConcurrentService(FakeService):
        calls = 0

        async def cancel(self, task_id):
            index = self.calls
            self.calls += 1
            entered[index].set()
            await released[index].wait()
            return await super().cancel(task_id)

    service = ConcurrentService()
    async with httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.ASGITransport(
            app=create_app(settings(tmp_path), service=service)
        ),
    ) as http:
        path = "/internal/tasks/parse_fixture/cancel"
        first = asyncio.create_task(
            http.post(
                path,
                content=b"{}",
                headers=signed_headers(path, b"{}", "concurrent_first_nonce"),
            )
        )
        await entered[0].wait()
        second = asyncio.create_task(
            http.post(
                path,
                content=b"{}",
                headers=signed_headers(path, b"{}", "concurrent_second_nonce"),
            )
        )
        await entered[1].wait()
        released[0].set()
        first_ack = await first
        inspect_path = "/internal/inspect"
        body = json.dumps(
            inspect_document(
                "https://media.example.com/video",
                cleanup_token=first_ack.json()["cleanup_token"],
            )
        ).encode()
        during = await http.post(
            inspect_path,
            content=body,
            headers=signed_headers(inspect_path, body, "concurrent_during_nonce"),
        )
        assert during.status_code == 409
        released[1].set()
        second_ack = await second
        assert first_ack.json()["cleanup_token"] == second_ack.json()["cleanup_token"]
        resumed = await http.post(
            inspect_path,
            content=body,
            headers=signed_headers(inspect_path, body, "concurrent_after_nonce"),
        )
        assert resumed.status_code == 200


async def test_previously_authenticated_delayed_request_rechecks_signature_age(
    tmp_path, monkeypatch
):
    import asyncio

    import httpx

    now = datetime.now(UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr("app.workers.runner.main.datetime", Clock)
    monkeypatch.setattr("app.workers.runner.main.time.time", lambda: now.timestamp())
    admitted, release = asyncio.Event(), asyncio.Event()

    async def postpone(_request, operation):
        admitted.set()
        await release.wait()
        return await operation

    monkeypatch.setattr("app.workers.runner.main._until_disconnect", postpone)
    service = FakeService()
    async with httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.ASGITransport(
            app=create_app(settings(tmp_path), service=service)
        ),
    ) as http:
        path = "/internal/inspect"
        body = json.dumps(
            inspect_document(
                "https://media.example.com/video",
                issued_at=now.isoformat(),
                deadline=(now + timedelta(seconds=120)).isoformat(),
            )
        ).encode()
        pending = asyncio.create_task(
            http.post(
                path,
                content=body,
                headers=signed_headers(path, body, "authenticated_old_nonce"),
            )
        )
        await admitted.wait()
        cancel_path = "/internal/tasks/parse_fixture/cancel"
        ack = await http.post(
            cancel_path,
            content=b"{}",
            headers=signed_headers(cancel_path, b"{}", "authenticated_cancel_nonce"),
        )
        assert ack.status_code == 200
        now += timedelta(seconds=37)
        release.set()
        response = await pending
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "signature_expired"
        assert service.inspected_url is None


async def test_cancel_cleanup_longer_than_signed_lifetime_keeps_pending_barrier(
    tmp_path, monkeypatch
):
    import asyncio

    import httpx

    now = datetime.now(UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr("app.workers.runner.main.datetime", Clock)
    monkeypatch.setattr("app.workers.runner.main.time.time", lambda: now.timestamp())
    entered, release = asyncio.Event(), asyncio.Event()

    class CleaningService(FakeService):
        async def cancel(self, task_id):
            entered.set()
            await release.wait()
            return await super().cancel(task_id)

    configured = settings(tmp_path).model_copy(
        update={
            "runner_signature_max_age_seconds": 1,
            "runner_signature_future_skew_seconds": 0,
        }
    )
    service = CleaningService()
    async with httpx.AsyncClient(
        base_url="http://runner",
        transport=httpx.ASGITransport(app=create_app(configured, service=service)),
    ) as http:
        cancel_path = "/internal/tasks/parse_fixture/cancel"
        pending = asyncio.create_task(
            http.post(
                cancel_path,
                content=b"{}",
                headers=signed_headers(
                    cancel_path, b"{}", "short_lifetime_cancel_nonce"
                ),
            )
        )
        await entered.wait()
        now += timedelta(seconds=10)
        path = "/internal/inspect"
        body = json.dumps(
            inspect_document(
                "https://media.example.com/video",
                issued_at=now.isoformat(),
                deadline=(now + timedelta(seconds=120)).isoformat(),
            )
        ).encode()
        response = await http.post(
            path,
            content=body,
            headers=signed_headers(path, body, "short_lifetime_admission_nonce"),
        )
        assert response.status_code == 409
        assert service.inspected_url is None
        release.set()
        assert (await pending).status_code == 200
