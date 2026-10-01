from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from app.services.auth.models import CurrentUser, UserRole
from app.services.provider_catalog import (
    DuplicateProviderCatalogKeyError,
    ProviderCatalogEntry,
    ProviderCatalogError,
    ProviderCatalogErrorCode,
    ProviderCatalogService,
)
from app.services.provider_types import ProviderIdentity, ProviderSupportStatus
from app.services.providers import ProviderStatusView

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


class Repository:
    def __init__(self) -> None:
        self.entries: dict[str, ProviderCatalogEntry] = {}

    async def list_entries(
        self, *, visible_only: bool = False
    ) -> tuple[ProviderCatalogEntry, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self.entries.values()
                    if not visible_only or item.is_visible
                ),
                key=lambda item: (item.sort_order, item.key),
            )
        )

    async def create_entry(self, **values) -> ProviderCatalogEntry:
        key = values["key"]
        if key in self.entries:
            raise DuplicateProviderCatalogKeyError
        entry = ProviderCatalogEntry(
            key=key,
            display_name=values["display_name"],
            sort_order=values["sort_order"],
            is_visible=values["is_visible"],
            created_at=values["now"],
            updated_at=values["now"],
        )
        self.entries[key] = entry
        return entry

    async def update_entry(self, key: str, **values) -> ProviderCatalogEntry | None:
        current = self.entries.get(key)
        if current is None:
            return None
        entry = ProviderCatalogEntry(
            key=key,
            display_name=values["display_name"] or current.display_name,
            sort_order=(
                current.sort_order
                if values["sort_order"] is None
                else values["sort_order"]
            ),
            is_visible=(
                current.is_visible
                if values["is_visible"] is None
                else values["is_visible"]
            ),
            created_at=current.created_at,
            updated_at=values["now"],
        )
        self.entries[key] = entry
        return entry

    async def delete_entry(self, key: str, *, now: datetime) -> bool:
        _ = now
        return self.entries.pop(key, None) is not None


def service(repository: Repository) -> ProviderCatalogService:
    baseline = ProviderStatusView(
        key="vimeo",
        display_name="Vimeo",
        registered=True,
        extractor_exists=True,
        capabilities=(),
        identity=ProviderIdentity.NONE,
        status=ProviderSupportStatus.UNKNOWN,
        user_action=None,
    )
    return ProviderCatalogService(repository, (baseline,), now=lambda: NOW)


@pytest.mark.asyncio
async def test_admin_crud_distinguishes_catalog_from_system_capability() -> None:
    repository = Repository()
    catalog = service(repository)

    custom = await catalog.create_entry(
        ADMIN,
        key="custom_media",
        display_name="  Custom   Media  ",
        sort_order=20,
        is_visible=True,
    )
    vimeo = await catalog.create_entry(
        ADMIN,
        key="vimeo",
        display_name="Vimeo 视频",
        sort_order=10,
        is_visible=True,
    )

    assert custom.entry.display_name == "Custom Media"
    assert custom.system_registered is False
    assert custom.system_status is ProviderSupportStatus.UNSUPPORTED
    assert vimeo.system_registered is True
    assert [item.entry.key for item in await catalog.list_entries(ADMIN)] == [
        "vimeo",
        "custom_media",
    ]

    updated = await catalog.update_entry(
        ADMIN,
        "custom_media",
        display_name="自定义媒体",
        sort_order=5,
        is_visible=False,
    )
    assert updated.entry.display_name == "自定义媒体"
    assert updated.entry.is_visible is False
    await catalog.delete_entry(ADMIN, "custom_media")
    assert [item.entry.key for item in await catalog.list_entries(ADMIN)] == ["vimeo"]


@pytest.mark.asyncio
async def test_catalog_rejects_non_admin_duplicates_and_missing_entries() -> None:
    repository = Repository()
    catalog = service(repository)
    values = {
        "key": "vimeo",
        "display_name": "Vimeo",
        "sort_order": 10,
        "is_visible": True,
    }
    with pytest.raises(ProviderCatalogError) as forbidden:
        await catalog.create_entry(USER, **values)
    assert forbidden.value.code is ProviderCatalogErrorCode.FORBIDDEN

    await catalog.create_entry(ADMIN, **values)
    with pytest.raises(ProviderCatalogError) as duplicate:
        await catalog.create_entry(ADMIN, **values)
    assert duplicate.value.code is ProviderCatalogErrorCode.CONFLICT

    with pytest.raises(ProviderCatalogError) as missing:
        await catalog.delete_entry(ADMIN, "missing")
    assert missing.value.code is ProviderCatalogErrorCode.NOT_FOUND
