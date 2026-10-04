from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.api.admission import RateLimitAdmission, _client_host
from app.api.deps import get_current_user
from app.core.config import Settings
from app.integrations.rate_limiter import RateLimitExceeded
from app.main import create_app
from fastapi.testclient import TestClient
from starlette.requests import Request


def _network_request(peer: str, forwarded_for: str | None = None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": headers,
            "client": (peer, 12345),
            "server": ("testserver", 80),
        }
    )


def test_client_host_uses_the_nearest_untrusted_forwarded_address() -> None:
    trusted = ("127.0.0.0/8", "172.30.99.10/32")
    request = _network_request(
        "172.30.99.10", "203.0.113.200, 198.51.100.24, 172.30.99.10"
    )

    assert _client_host(request, trusted) == "198.51.100.24"


def test_client_host_ignores_forwarding_headers_from_untrusted_peers() -> None:
    request = _network_request("198.51.100.24", "203.0.113.200")

    assert _client_host(request, ("127.0.0.0/8",)) == "198.51.100.24"


def test_client_host_fails_closed_for_a_malformed_forwarding_chain() -> None:
    request = _network_request("127.0.0.1", "203.0.113.200, invalid")

    assert _client_host(request, ("127.0.0.0/8",)) == "127.0.0.1"


@pytest.mark.parametrize(
    "path",
    [
        "/api/downloads/00000000-0000-0000-0000-000000000001/analyses",
        "/api/documents/00000000-0000-0000-0000-000000000001/analyses",
        "/api/analyses/00000000-0000-0000-0000-000000000001/retry",
    ],
)
def test_all_analysis_creation_routes_enforce_admission(path: str) -> None:
    app = create_app(Settings(app_env="test", _env_file=None))
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        owner_hash="a" * 64, is_admin=False
    )

    class Limiter:
        async def check(self, **kwargs):
            assert kwargs["operation"] in {"analysis", "analysis_retry"}
            raise RateLimitExceeded(9)

    app.state.services.rate_limiter = Limiter()
    with TestClient(app) as client:
        response = client.post(path, json={}, headers={"Idempotency-Key": "review"})
    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert response.headers["Retry-After"] == "9"


def test_costly_routes_declare_admission_and_recovery_routes_remain_available() -> None:
    from app.api.routes import (
        analyses,
        document_analyses,
        documents,
        downloads,
        inspections,
        media_imports,
        source_discoveries,
    )

    expected = {
        "inspectMedia",
        "createSourceDiscovery",
        "createDownload",
        "retryDownload",
        "createMediaImport",
        "createMediaUploadSession",
        "completeMediaImport",
        "createDocumentImport",
        "createDocumentUploadSession",
        "completeDocumentImport",
        "createAnalysis",
        "createDocumentAnalysis",
        "retryAnalysis",
    }
    found = set()
    for module in (
        analyses,
        document_analyses,
        documents,
        downloads,
        inspections,
        media_imports,
        source_discoveries,
    ):
        for route in module.router.routes:
            limited = any(
                isinstance(dep.call, RateLimitAdmission)
                for dep in route.dependant.dependencies
            )
            if limited:
                found.add(route.operation_id)
            if route.operation_id.startswith(
                ("get", "cancel", "delete", "list", "export")
            ):
                assert not limited
    assert found == expected
