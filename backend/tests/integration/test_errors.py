from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.api.errors import application_error
from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.services.downloads.errors import ApplicationError, ApplicationErrorCode
from fastapi import Response
from fastapi.testclient import TestClient


def test_transient_failure_exposes_bounded_retry_header():
    mapped = application_error(
        ApplicationError(
            ApplicationErrorCode.TRANSIENT,
            retry_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    )
    assert mapped.status == 503
    assert mapped.headers is not None
    assert 299 <= int(mapped.headers["Retry-After"]) <= 300
    assert "egress" not in mapped.detail


def test_media_rate_limit_preserves_429_and_retry_after():
    app = create_app(Settings(app_env="test"))

    @app.get("/api/provider-limited")
    async def provider_limited():
        raise ApplicationError(
            ApplicationErrorCode.RATE_LIMITED,
            retry_at=datetime.now(UTC) + timedelta(seconds=30),
        )

    with TestClient(app) as client:
        result = client.get("/api/provider-limited")

    assert result.status_code == 429
    assert result.json()["code"] == "rate_limited"
    assert 29 <= int(result.headers["Retry-After"]) <= 30


def test_identity_and_changed_context_keep_distinct_actionable_errors():
    assert (
        application_error(
            ApplicationError(ApplicationErrorCode.IDENTITY_UNAVAILABLE)
        ).status
        == 503
    )
    changed = application_error(ApplicationError(ApplicationErrorCode.CONTEXT_CHANGED))
    assert changed.status == 409
    assert changed.code == "context_changed"
    assert "Resolve again" in changed.detail


def test_app_error_uses_stable_error_envelopes(tmp_path: Path) -> None:
    app = create_app(Settings(app_env="test"))

    @app.get("/api/test-error")
    async def test_error() -> None:
        raise AppError(
            status=409,
            code="job_conflict",
            title="Job conflict",
            detail="The job cannot transition from its current state.",
        )

    with TestClient(app) as client:
        response = client.get("/api/test-error")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "code": "job_conflict",
        "message": "The job cannot transition from its current state.",
        "data": None,
    }


def test_request_validation_uses_stable_error_envelopes(tmp_path: Path) -> None:
    app = create_app(Settings(app_env="test"))

    @app.get("/api/validation")
    async def validation(limit: int) -> dict[str, int]:
        return {"limit": limit}

    with TestClient(app) as client:
        response = client.get("/api/validation", params={"limit": "invalid"})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "code": "invalid_request",
        "message": "The request parameters are invalid.",
        "data": None,
    }


def test_global_errors_keep_status_headers_and_hide_internal_input() -> None:
    from fastapi import HTTPException

    app = create_app(Settings(app_env="test"))

    @app.get("/api/crash")
    def crash() -> None:
        raise RuntimeError("secret-database-password")

    @app.get("/api/limited")
    def limited() -> None:
        raise HTTPException(429, "secret-upstream", headers={"Retry-After": "17"})

    with TestClient(app) as client:
        for method, path, status, code in (
            ("get", "/api/missing", 404, "not_found"),
            ("post", "/api/limited", 405, "method_not_allowed"),
            ("get", "/api/crash", 500, "internal_error"),
            ("get", "/api/limited", 429, "operation_rate_limited"),
        ):
            response = client.request(method, path)
            assert response.status_code == status
            assert set(response.json()) == {"code", "message", "data"}
            assert response.json()["code"] == code
            assert response.json()["data"] is None
            assert "secret" not in response.text
            assert response.headers["x-content-type-options"] == "nosniff"
            if status == 405:
                assert "GET" in response.headers["allow"]
            if status == 429:
                assert response.headers["retry-after"] == "17"


def test_typed_envelopes_validate_data_and_preserve_non_json_protocols() -> None:
    from app.api.responses import ApiResponseRoute
    from fastapi import APIRouter
    from pydantic import BaseModel

    class PublicItem(BaseModel):
        name: str

    app = create_app(Settings(app_env="test"))
    router = APIRouter(route_class=ApiResponseRoute)

    @router.get("/api/item", response_model=PublicItem)
    def item():
        return {"name": "public", "password": "secret"}

    @router.get("/api/items", response_model=list[PublicItem])
    async def items():
        return [{"name": "public"}]

    @router.get("/api/broken", response_model=PublicItem)
    async def broken():
        return {"password": "secret"}

    @router.get("/api/empty", status_code=204)
    async def empty() -> None:
        return None

    @router.get("/api/file")
    async def file() -> Response:
        return Response(b"file-bytes", media_type="application/octet-stream")

    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/api/item").json() == {
            "code": "ok",
            "message": "OK",
            "data": {"name": "public"},
        }
        assert client.get("/api/items").json()["data"] == [{"name": "public"}]
        invalid = client.get("/api/broken")
        assert invalid.status_code == 500
        assert invalid.json()["code"] == "internal_error"
        assert "password" not in invalid.text
        assert client.get("/api/empty").content == b""
        binary = client.get("/api/file")
        assert binary.content == b"file-bytes"
        assert binary.headers["content-type"] == "application/octet-stream"
    schema = app.openapi()
    ref = schema["paths"]["/api/item"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].split("/")[-1]
    envelope = schema["components"]["schemas"][ref]
    assert envelope["required"] == ["code", "message", "data"]
    assert envelope["properties"]["data"]["$ref"] == "#/components/schemas/PublicItem"


async def test_timeout_uses_global_error_contract_and_security_headers() -> None:
    from unittest.mock import AsyncMock

    from app.api.middleware import request_guard
    from starlette.requests import Request

    receive = AsyncMock(return_value={"type": "http.request", "body": b""})
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "app": create_app(Settings(app_env="test")),
            "path": "/api/slow",
            "headers": [],
        },
        receive,
    )
    response = await request_guard(
        request,
        AsyncMock(side_effect=TimeoutError),
        max_body_bytes=1024,
        timeout_seconds=1,
        production=False,
    )
    import json

    assert response.status_code == 504
    assert json.loads(response.body) == {
        "code": "request_timeout",
        "message": "The request exceeded its deadline.",
        "data": None,
    }
    assert response.headers["x-content-type-options"] == "nosniff"
