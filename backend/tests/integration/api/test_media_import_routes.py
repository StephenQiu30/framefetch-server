from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.api.deps import get_current_user
from app.core.config import Settings
from app.core.runtime import MediaImportUseCases
from app.main import create_app
from app.services.auth.models import CurrentUser, UserRole
from app.services.imports.errors import (
    ImportApplicationError,
    ImportApplicationErrorCode,
)
from app.services.imports.models import ImportView, UploadPartTarget, UploadSessionView
from app.services.imports.rules.enums import (
    ContentKind,
    ImportSourceFormat,
    ImportStatus,
)
from fastapi.testclient import TestClient

NOW = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
RESOURCE_ID = UUID("11111111-1111-4111-8111-111111111111")
TEST_USER = CurrentUser(
    id=RESOURCE_ID,
    username="video_user",
    email="user@example.com",
    role=UserRole.USER,
    created_at=NOW,
    updated_at=NOW,
)


class StubUseCase:
    def __init__(self, result: object) -> None:
        self.result = result
        self.error: ImportApplicationError | None = None
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def __call__(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


def import_view(status: ImportStatus = ImportStatus.UPLOADING) -> ImportView:
    return ImportView(
        id=RESOURCE_ID,
        content_kind=ContentKind.VIDEO,
        source_format=ImportSourceFormat.MP4,
        display_name="owned.mp4",
        declared_size_bytes=5 * 1024**2 + 1,
        status=status,
        attempt=1,
        error_code=None,
        version=2,
        created_at=NOW,
        updated_at=NOW,
        finished_at=None,
    )


def upload_session_view() -> UploadSessionView:
    return UploadSessionView(
        resource_id=RESOURCE_ID,
        attempt=1,
        part_size_bytes=5 * 1024**2,
        part_count=2,
        max_concurrency=4,
        expires_at=NOW + timedelta(minutes=15),
        parts=(
            UploadPartTarget(1, "https://objects.example/part/1?signature=private"),
            UploadPartTarget(2, "https://objects.example/part/2?signature=private"),
        ),
    )


def client(
    tmp_path: Path,
) -> tuple[TestClient, dict[str, StubUseCase]]:
    app = create_app(Settings(app_env="test"))
    stubs = {
        "create": StubUseCase(import_view()),
        "session": StubUseCase(upload_session_view()),
        "complete": StubUseCase(import_view(ImportStatus.VERIFYING)),
        "get": StubUseCase(import_view()),
        "cancel": StubUseCase(import_view(ImportStatus.CANCELLED)),
    }
    app.state.services.media_import_use_cases = MediaImportUseCases(
        create_resource=stubs["create"],  # type: ignore[arg-type]
        create_upload_session=stubs["session"],  # type: ignore[arg-type]
        complete_upload=stubs["complete"],  # type: ignore[arg-type]
        get_import=stubs["get"],  # type: ignore[arg-type]
        cancel_import=stubs["cancel"],  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    return TestClient(app), stubs


def request_body() -> dict[str, object]:
    return {
        "file_name": "owned.mp4",
        "declared_size_bytes": 5 * 1024**2 + 1,
        "declared_sha256": "b" * 64,
        "rights_accepted": True,
    }


def test_media_import_use_cases_are_resolved_from_app_state(tmp_path: Path) -> None:
    app = create_app(Settings(app_env="test"))
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/media-imports",
            headers={"Idempotency-Key": "import-1"},
            json=request_body(),
        )

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"


def test_media_import_routes_delegate_owner_and_hide_storage_identity(
    tmp_path: Path,
) -> None:
    test_client, stubs = client(tmp_path)
    parts = [
        {"part_number": 1, "etag": "1" * 32},
        {"part_number": 2, "etag": '"' + "2" * 32 + '"'},
    ]
    with test_client:
        created = test_client.post(
            "/api/media-imports",
            headers={"Idempotency-Key": "import-1"},
            json=request_body(),
        )
        fetched = test_client.get(f"/api/media-imports/{RESOURCE_ID}")
        session = test_client.post(f"/api/media-imports/{RESOURCE_ID}/upload-sessions")
        completed = test_client.post(
            f"/api/media-imports/{RESOURCE_ID}/complete",
            json={"parts": parts},
        )

    assert created.status_code == session.status_code == 201
    assert fetched.status_code == completed.status_code == 200
    assert created.headers["location"] == f"/api/media-imports/{RESOURCE_ID}"
    assert created.headers["cache-control"] == "no-store"
    assert created.json()["data"]["download_id"] == str(RESOURCE_ID)
    assert completed.json()["data"]["status"] == "verifying"
    assert session.json()["data"]["part_count"] == 2
    assert session.json()["data"]["max_concurrency"] == 4
    assert "object_key" not in session.text
    assert "upload_id" not in session.text
    create_kwargs = stubs["create"].calls[0][1]
    assert create_kwargs["owner_hash"] == TEST_USER.owner_hash
    assert create_kwargs["source_format"] is ImportSourceFormat.MP4
    assert create_kwargs["content_kind"] is ContentKind.VIDEO
    assert create_kwargs["idempotency_key"] == "import-1"
    assert create_kwargs["declared_origin"].value == "user_file"
    complete_args = stubs["complete"].calls[0][0]
    assert complete_args[:3] == (
        RESOURCE_ID,
        TEST_USER.owner_hash,
        ContentKind.VIDEO,
    )
    assert tuple(part.etag for part in complete_args[3]) == (
        "1" * 32,
        '"' + "2" * 32 + '"',
    )


def test_media_import_request_rejects_client_storage_controls(tmp_path: Path) -> None:
    test_client, stubs = client(tmp_path)
    body = request_body() | {
        "bucket": "another-bucket",
        "object_key": "downloads/foreign/video.mp4",
        "content_type": "application/octet-stream",
        "part_size_bytes": 1,
    }
    with test_client:
        response = test_client.post(
            "/api/media-imports",
            headers={"Idempotency-Key": "import-1"},
            json=body,
        )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert stubs["create"].calls == []


def test_media_import_request_does_not_coerce_rights_or_size(tmp_path: Path) -> None:
    test_client, stubs = client(tmp_path)
    with test_client:
        numeric_rights = test_client.post(
            "/api/media-imports",
            headers={"Idempotency-Key": "import-1"},
            json=request_body() | {"rights_accepted": 1},
        )
        boolean_size = test_client.post(
            "/api/media-imports",
            headers={"Idempotency-Key": "import-2"},
            json=request_body() | {"declared_size_bytes": True},
        )

    assert numeric_rights.status_code == boolean_size.status_code == 422
    assert stubs["create"].calls == []


def test_media_import_errors_use_stable_error_envelopes(tmp_path: Path) -> None:
    test_client, stubs = client(tmp_path)
    stubs["create"].error = ImportApplicationError(ImportApplicationErrorCode.DISABLED)
    stubs["session"].error = ImportApplicationError(
        ImportApplicationErrorCode.STORAGE_UNAVAILABLE
    )
    with test_client:
        disabled = test_client.post(
            "/api/media-imports",
            headers={"Idempotency-Key": "import-1"},
            json=request_body(),
        )
        unavailable = test_client.post(
            f"/api/media-imports/{RESOURCE_ID}/upload-sessions"
        )

    assert disabled.status_code == unavailable.status_code == 503
    assert disabled.json()["code"] == "import_disabled"
    assert unavailable.json()["code"] == "import_storage_unavailable"


def test_media_import_openapi_is_strict_and_has_unique_operations(
    tmp_path: Path,
) -> None:
    schema = create_app(Settings(app_env="test")).openapi()
    paths = schema["paths"]
    assert paths["/api/media-imports"]["post"]["operationId"] == ("createMediaImport")
    assert paths["/api/media-imports/{resource_id}"]["get"]["operationId"] == (
        "getMediaImport"
    )
    assert (
        paths["/api/media-imports/{resource_id}/upload-sessions"]["post"]["operationId"]
        == "createMediaUploadSession"
    )
    assert (
        paths["/api/media-imports/{resource_id}/complete"]["post"]["operationId"]
        == "completeMediaImport"
    )
    components = schema["components"]["schemas"]
    request = components["MediaImportRequest"]
    assert request["additionalProperties"] is False
    assert set(request["properties"]) == {
        "file_name",
        "declared_size_bytes",
        "declared_sha256",
        "declared_origin",
        "rights_accepted",
        "remove_watermark",
    }
    assert request["properties"]["remove_watermark"]["type"] == "boolean"
    assert request["properties"]["remove_watermark"]["default"] is False
    assert "remove_watermark" not in request["required"]
    serialized = str(paths).casefold()
    assert "minio_import" not in serialized
    assert "upload_id" not in serialized
    assert "object_key" not in serialized


def test_media_import_accepts_only_controlled_wechat_channels_origin(
    tmp_path: Path,
) -> None:
    test_client, stubs = client(tmp_path)
    with test_client:
        accepted = test_client.post(
            "/api/media-imports",
            headers={"Idempotency-Key": "wechat-import"},
            json=request_body() | {"declared_origin": "wechat_channels"},
        )
        rejected = test_client.post(
            "/api/media-imports",
            headers={"Idempotency-Key": "unknown-import"},
            json=request_body() | {"declared_origin": "arbitrary_platform"},
        )

    assert accepted.status_code == 201
    assert rejected.status_code == 422
    assert stubs["create"].calls[0][1]["declared_origin"].value == ("wechat_channels")
