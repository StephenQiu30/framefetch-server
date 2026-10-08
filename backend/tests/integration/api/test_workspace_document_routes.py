from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from app.api.deps import get_current_admin, get_current_user
from app.core.config import Settings
from app.main import create_app
from app.services.auth.models import CurrentUser, UserRole
from app.services.workspace_documents.rules import content_digest
from fastapi.testclient import TestClient

NOW = datetime(2026, 10, 6, tzinfo=UTC)
ADMIN = CurrentUser(
    UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    "admin",
    "admin@example.com",
    UserRole.ADMIN,
    NOW,
    NOW,
)
USER = CurrentUser(
    UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
    "user",
    "user@example.com",
    UserRole.USER,
    NOW,
    NOW,
)
PATH = "design/01-边界.md"
ORIGINAL = "# 产品边界\n\n正文\n"


@pytest.fixture
def content(tmp_path: Path) -> Path:
    (tmp_path / "design").mkdir()
    (tmp_path / PATH).write_text(ORIGINAL, encoding="utf-8")
    return tmp_path


def _client(content: Path) -> TestClient:
    return TestClient(
        create_app(Settings(app_env="test", workspace_content_dir=content))
    )


def test_documents_are_publicly_readable(content: Path) -> None:
    with _client(content) as client:
        listing = client.get("/api/workspace/documents")
        document = client.get("/api/workspace/document", params={"path": PATH})
    assert listing.json()["data"]["items"] == [
        {"path": PATH, "title": "产品边界", "section": "design"}
    ]
    assert document.json()["data"]["sha256"] == content_digest(ORIGINAL)


def test_admin_saves_against_the_loaded_version(content: Path) -> None:
    app = create_app(Settings(app_env="test", workspace_content_dir=content))
    app.dependency_overrides[get_current_admin] = lambda: ADMIN
    body = {"content": "# 新标题\n\n内容\n", "base_sha256": content_digest(ORIGINAL)}
    with TestClient(app) as client:
        saved = client.put("/api/workspace/document", params={"path": PATH}, json=body)
        stale = client.put("/api/workspace/document", params={"path": PATH}, json=body)
    assert saved.status_code == 200
    assert saved.json()["data"]["title"] == "新标题"
    assert (content / PATH).read_text(encoding="utf-8") == "# 新标题\n\n内容\n"
    assert stale.status_code == 409
    assert stale.json()["code"] == "workspace_document_conflict"


def test_saving_requires_an_administrator(content: Path) -> None:
    app = create_app(Settings(app_env="test", workspace_content_dir=content))
    app.dependency_overrides[get_current_user] = lambda: USER
    body = {"content": "# 改写\n", "base_sha256": content_digest(ORIGINAL)}
    with TestClient(app) as client:
        response = client.put(
            "/api/workspace/document", params={"path": PATH}, json=body
        )
    assert response.status_code == 403
    assert (content / PATH).read_text(encoding="utf-8") == ORIGINAL


def test_missing_workspace_directory_is_reported(tmp_path: Path) -> None:
    with _client(tmp_path / "absent") as client:
        response = client.get("/api/workspace/documents")
    assert response.status_code == 503
    assert response.json()["code"] == "workspace_unavailable"
