from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.api.deps import get_current_admin, get_current_user
from app.core.config import Settings
from app.main import create_app
from app.services.auth.models import CurrentUser, UserRole
from app.services.storage_files.models import (
    StorageCleanupResult,
    StoredFilePage,
    StoredFileView,
)
from fastapi.testclient import TestClient

NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)
LONG_FILE_NAME = "超长视频标题" * 30
ADMIN = CurrentUser(
    id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    username="admin_user",
    email="admin@example.com",
    role=UserRole.ADMIN,
    created_at=NOW,
    updated_at=NOW,
)
USER = CurrentUser(
    id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
    username="normal_user",
    email="user@example.com",
    role=UserRole.USER,
    created_at=NOW,
    updated_at=NOW,
)


class StorageFilesStub:
    def __init__(self) -> None:
        self.uploader_username: str | None = USER.username
        self.list_calls: list[tuple[int, int]] = []
        self.cleanup_calls: list[int] = []
        self.delete_calls: list[tuple[str, UUID]] = []

    async def list_files(self, *, page: int, page_size: int) -> StoredFilePage:
        self.list_calls.append((page, page_size))
        return StoredFilePage(
            items=(
                StoredFileView(
                    id=UUID("11111111-1111-4111-8111-111111111111"),
                    category="video",
                    name=LONG_FILE_NAME,
                    uploader_username=self.uploader_username,
                    object_count=1,
                    size_bytes=1024,
                    created_at=NOW,
                ),
            ),
            page=page,
            page_size=page_size,
            total=21,
        )

    async def cleanup(self, *, older_than_days: int) -> StorageCleanupResult:
        self.cleanup_calls.append(older_than_days)
        return StorageCleanupResult(older_than_days, 2, 3, 4096, 0)

    async def delete_file(self, *, category: str, file_id: UUID) -> None:
        self.delete_calls.append((category, file_id))


def _app(tmp_path: Path, stub: StorageFilesStub):
    app = create_app(Settings(app_env="test"))
    app.state.services.storage_file_service = stub
    return app


def test_admin_files_are_paginated_and_cleanup_defaults_to_thirty_days(
    tmp_path: Path,
) -> None:
    stub = StorageFilesStub()
    app = _app(tmp_path, stub)
    app.dependency_overrides[get_current_admin] = lambda: ADMIN

    with TestClient(app) as client:
        listing = client.get("/api/admin/files", params={"page": 2, "page_size": 10})
        cleanup = client.post("/api/admin/files/cleanup", json={})

    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 21
    assert listing.json()["data"]["items"][0]["name"] == LONG_FILE_NAME
    assert listing.json()["data"]["items"][0]["uploader_username"] == USER.username
    assert "owner_hash" not in listing.text
    assert "password" not in listing.text
    assert "object_key" not in listing.text
    assert stub.list_calls == [(2, 10)]
    assert cleanup.status_code == 200
    assert cleanup.json()["data"] == {
        "older_than_days": 30,
        "removed_resources": 2,
        "removed_objects": 3,
        "freed_bytes": 4096,
        "failed_resources": 0,
    }
    assert stub.cleanup_calls == [30]


def test_files_without_an_account_keep_their_record(tmp_path: Path) -> None:
    stub = StorageFilesStub()
    stub.uploader_username = None
    app = _app(tmp_path, stub)
    app.dependency_overrides[get_current_admin] = lambda: ADMIN
    with TestClient(app) as client:
        listing = client.get("/api/admin/files")
    assert listing.status_code == 200
    assert listing.json()["data"]["items"][0]["uploader_username"] is None
    assert listing.json()["data"]["total"] == 21


def test_admin_files_reject_non_admin(tmp_path: Path) -> None:
    stub = StorageFilesStub()
    app = _app(tmp_path, stub)
    app.dependency_overrides[get_current_user] = lambda: USER

    with TestClient(app) as client:
        listing = client.get("/api/admin/files")
        cleanup = client.post("/api/admin/files/cleanup", json={"older_than_days": 30})
        deletion = client.delete(
            "/api/admin/files/video/11111111-1111-4111-8111-111111111111"
        )

    assert listing.status_code == cleanup.status_code == deletion.status_code == 403
    assert stub.list_calls == []
    assert stub.cleanup_calls == []
    assert stub.delete_calls == []


def test_admin_can_delete_one_persistent_file(tmp_path: Path) -> None:
    stub = StorageFilesStub()
    app = _app(tmp_path, stub)
    app.dependency_overrides[get_current_admin] = lambda: ADMIN

    file_id = UUID("11111111-1111-4111-8111-111111111111")
    with TestClient(app) as client:
        response = client.delete(f"/api/admin/files/video/{file_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert stub.delete_calls == [("video", file_id)]
