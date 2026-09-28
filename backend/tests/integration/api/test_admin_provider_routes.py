from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.api.deps import get_current_admin, get_current_user
from app.core.config import Settings
from app.main import create_app
from app.services.auth.models import CurrentUser, UserRole
from app.services.provider_catalog import (
    ManagedProviderCatalogEntry,
    ProviderCatalogEntry,
)
from app.services.provider_types import ProviderSupportStatus
from fastapi.testclient import TestClient

NOW = datetime(2026, 8, 12, tzinfo=UTC)
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


class Catalog:
    def __init__(self) -> None:
        self.items: dict[str, ManagedProviderCatalogEntry] = {}

    async def list_entries(self, actor: CurrentUser):
        assert actor == ADMIN
        return tuple(self.items.values())

    async def create_entry(self, actor: CurrentUser, **values):
        assert actor == ADMIN
        entry = ProviderCatalogEntry(
            **values,
            created_at=NOW,
            updated_at=NOW,
        )
        managed = ManagedProviderCatalogEntry(
            entry,
            system_registered=entry.key == "vimeo",
            system_status=ProviderSupportStatus.UNKNOWN,
        )
        self.items[entry.key] = managed
        return managed

    async def update_entry(self, actor: CurrentUser, key: str, **values):
        assert actor == ADMIN
        current = self.items[key]
        entry = replace(
            current.entry,
            display_name=values["display_name"] or current.entry.display_name,
            sort_order=(values["sort_order"] or current.entry.sort_order),
            is_visible=(
                current.entry.is_visible
                if values["is_visible"] is None
                else values["is_visible"]
            ),
            updated_at=NOW,
        )
        managed = replace(current, entry=entry)
        self.items[key] = managed
        return managed

    async def delete_entry(self, actor: CurrentUser, key: str) -> None:
        assert actor == ADMIN
        self.items.pop(key)


def test_admin_can_create_list_update_and_delete_provider_catalog_entries(
    tmp_path: Path,
) -> None:
    app = create_app(Settings(app_env="test"))
    app.state.services.provider_catalog_service = Catalog()
    app.dependency_overrides[get_current_admin] = lambda: ADMIN

    with TestClient(app) as client:
        created = client.post(
            "/api/admin/providers",
            json={
                "key": "vimeo",
                "display_name": "Vimeo 视频",
                "sort_order": 10,
                "is_visible": True,
            },
        )
        listed = client.get("/api/admin/providers")
        updated = client.patch(
            "/api/admin/providers/vimeo",
            json={"display_name": "Vimeo", "is_visible": False},
        )
        deleted = client.delete("/api/admin/providers/vimeo")

    assert created.status_code == 201
    assert created.headers["location"] == "/api/admin/providers/vimeo"
    assert created.json()["data"]["system_registered"] is True
    assert listed.json()["data"]["items"][0]["display_name"] == "Vimeo 视频"
    assert updated.status_code == 200
    assert updated.json()["data"]["is_visible"] is False
    assert deleted.status_code == 204
    assert deleted.content == b""


def test_provider_catalog_routes_reject_non_admin(tmp_path: Path) -> None:
    app = create_app(Settings(app_env="test"))
    catalog = Catalog()
    app.state.services.provider_catalog_service = catalog
    app.dependency_overrides[get_current_user] = lambda: USER

    with TestClient(app) as client:
        response = client.get("/api/admin/providers")

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert catalog.items == {}
