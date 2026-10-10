from pathlib import Path

from app.core.config import Settings
from app.integrations.rate_limiter import RateLimitExceeded
from app.main import create_app
from fastapi.testclient import TestClient


def test_request_guard_rejects_large_bodies_and_adds_security_headers(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            app_env="test",
            request_max_bytes=1024,
        )
    )

    with TestClient(app, headers={"Origin": "http://testserver"}) as client:
        response = client.post("/health/live", content=b"x" * 1025)

    assert response.status_code == 413
    assert response.json()["code"] == "request_too_large"
    assert response.headers["x-content-type-options"] == "nosniff"
    csp = response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp
    assert "img-src 'self' data: blob: https:" in csp
    assert "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net" in csp


def test_request_guard_counts_streamed_bodies_without_content_length(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            app_env="test",
            request_max_bytes=1024,
        )
    )

    def chunks():
        yield b'{"email":"user@example.com","password":"'
        yield b"x" * 1024
        yield b'"}'

    with TestClient(app, headers={"Origin": "http://testserver"}) as client:
        response = client.post(
            "/api/auth/login",
            content=chunks(),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json()["code"] == "request_too_large"


def test_media_import_csp_allows_only_configured_storage_origin(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            app_env="test",
            media_import_enabled=True,
            minio_public_endpoint="storage.example.com:9443",
            minio_public_secure=True,
            _env_file=None,
        )
    )

    with TestClient(app, headers={"Origin": "http://testserver"}) as client:
        response = client.get("/health/live")

    csp = response.headers["content-security-policy"]
    assert "connect-src 'self' https://storage.example.com:9443" in csp
    assert "media-src 'self' https://storage.example.com:9443" in csp
    assert "connect-src *" not in csp
    assert "media-src *" not in csp


def test_document_import_enables_bounded_storage_origin(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            app_env="test",
            media_import_enabled=False,
            document_import_enabled=True,
            minio_public_endpoint="documents.example.com:9443",
            minio_public_secure=True,
            _env_file=None,
        )
    )

    with TestClient(app, headers={"Origin": "http://testserver"}) as client:
        csp = client.get("/health/live").headers["content-security-policy"]

    assert "connect-src 'self' https://documents.example.com:9443" in csp
    assert "media-src 'self';" in csp
    assert "media-src 'self' https://documents.example.com:9443" not in csp


def test_rate_limit_returns_problem_details_and_retry_after(tmp_path: Path) -> None:
    app = create_app(Settings(app_env="test"))

    class BlockedLimiter:
        async def check(self, **_kwargs: object) -> None:
            raise RateLimitExceeded(7)

    app.state.services.rate_limiter = BlockedLimiter()
    app.state.services.auth_service = object()
    app.state.services.web_session_service = object()
    with TestClient(app, headers={"Origin": "http://testserver"}) as client:
        response = client.post(
            "/api/auth/login",
            json={"email": "user@example.com", "password": "strong-pass-123"},
        )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "7"
    assert response.json()["code"] == "operation_rate_limited"
