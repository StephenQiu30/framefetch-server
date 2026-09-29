from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from api_helpers import FakeService, anonymous_access_context, settings, signed_headers
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
        "/internal/context",
        "/internal/contexts",
        "/internal/inspect",
        "/internal/download",
        "/internal/tasks/{task_id}",
        "/internal/tasks/{task_id}/cancel",
    }


def test_signed_inspect_forwards_frozen_context_and_aware_deadline(tmp_path):
    service = FakeService()
    client = TestClient(create_app(settings(tmp_path), service=service))
    deadline = datetime.now(UTC) + timedelta(seconds=20)
    body = json.dumps(
        {
            "url": "https://media.example.com/video",
            "access_context": anonymous_access_context(),
            "deadline_at": deadline.isoformat(),
        }
    ).encode()
    path = "/internal/inspect"
    response = client.post(
        path, content=body, headers=signed_headers(path, body, "deadline_nonce_123456")
    )
    assert response.status_code == 200
    assert service.inspected_context.to_document() == anonymous_access_context()
    assert service.inspect_deadline == deadline


def test_health_is_public_and_inspect_requires_valid_raw_body_signature(
    tmp_path: Path,
) -> None:
    service = FakeService()
    client = TestClient(create_app(settings(tmp_path), service=service))
    body = json.dumps({"url": "https://media.example.com/video"}).encode()
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


def test_context_endpoint_returns_only_signed_non_secret_runtime_refs(
    tmp_path: Path,
) -> None:
    service = FakeService()
    client = TestClient(create_app(settings(tmp_path), service=service))
    body = json.dumps({"url": "https://media.example.com/video"}).encode()
    path = "/internal/context"

    response = client.post(
        path,
        content=body,
        headers=signed_headers(path, body, "context_nonce_123456"),
    )

    assert response.status_code == 200
    assert response.json() == anonymous_access_context()
    assert set(response.json()) == {
        "provider_key",
        "profile_version",
        "access_mode",
        "credential_version_id",
        "egress_affinity_id",
        "client_profile_id",
        "attestation_provider_version",
        "engine_commit",
        "runtime_revision",
    }
    assert service.context_requests == ["https://media.example.com/video"]


def test_contexts_endpoint_resolves_a_signed_batch_without_network_input(
    tmp_path: Path,
) -> None:
    service = FakeService()
    client = TestClient(create_app(settings(tmp_path), service=service))
    body = json.dumps({"provider_keys": ["generic"]}).encode()
    path = "/internal/contexts"

    response = client.post(
        path,
        content=body,
        headers=signed_headers(path, body, "contexts_nonce_12345"),
    )

    assert response.status_code == 200
    assert response.json() == {"contexts": [anonymous_access_context()]}
    assert service.context_requests == ["generic"]


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
        ("/internal/context", {"url": "https://media.example.com/video"}),
        ("/internal/contexts", {"provider_keys": ["generic"]}),
        ("/internal/inspect", {"url": "https://media.example.com/video"}),
        (
            "/internal/download",
            {
                "task_id": "job_123",
                "url": "https://media.example.com/video",
                "expected_provider_media_id": "controlled",
                "expected_extractor_key": "Controlled",
                "access_context": anonymous_access_context(),
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
    body = json.dumps(payload).encode()

    response = client.post(
        path,
        content=body,
        headers=signed_headers(path, body, "engine_drift_nonce_12345"),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "engine_unavailable"
    assert service.context_requests == []
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
        "url": "https://media.example.com/video",
        "expected_provider_media_id": "controlled",
        "expected_extractor_key": "Controlled",
        "access_context": anonymous_access_context(),
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
            "url": "https://media.example.com/video",
            "expected_provider_media_id": "controlled",
            "expected_extractor_key": "Controlled",
            "access_context": anonymous_access_context(),
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
