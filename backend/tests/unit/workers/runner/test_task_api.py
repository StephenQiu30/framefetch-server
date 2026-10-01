from __future__ import annotations

from pathlib import Path

from api_helpers import FakeService, settings, signed_headers
from app.workers.runner.main import create_app
from fastapi.testclient import TestClient


def test_cancel_is_authenticated_and_idempotent(tmp_path: Path) -> None:
    service = FakeService()
    client = TestClient(create_app(settings(tmp_path), service=service))
    path = "/internal/tasks/job_123/cancel"

    responses = []
    for nonce in ("cancel_nonce_1234567", "cancel_nonce_7654321"):
        body = b"{}"
        responses.append(
            client.post(path, content=body, headers=signed_headers(path, body, nonce))
        )

    assert [response.status_code for response in responses] == [200, 200]
    for response in responses:
        facts = response.json()
        assert facts["task_id"] == "job_123"
        assert facts["status"] == "stopped"
        assert len(facts["cleanup_token"]) == 32
    assert responses[0].json()["cleanup_token"] != responses[1].json()["cleanup_token"]
    assert service.cancelled == ["job_123", "job_123"]


def test_task_status_get_is_hmac_authenticated(tmp_path: Path) -> None:
    service = FakeService()
    client = TestClient(create_app(settings(tmp_path), service=service))
    path = "/internal/tasks/job_123"
    headers = signed_headers(
        path,
        b"",
        "status_nonce_1234567",
        method="GET",
    )

    response = client.get(path, headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "job_123",
        "stage": "downloading",
        "progress": 40,
    }
    assert service.status_requests == ["job_123"]
