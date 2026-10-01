from __future__ import annotations

from app.schemas.common import StrictModel
from app.services.provider_types import (
    ProviderCapability,
    ProviderIdentity,
    ProviderSupportStatus,
)
from app.services.providers import ProviderStatusView


class ProviderStatusResponse(StrictModel):
    key: str
    display_name: str
    registered: bool
    extractor_exists: bool
    capabilities: tuple[ProviderCapability, ...]
    identity: ProviderIdentity
    status: ProviderSupportStatus
    download_supported: bool
    user_action: str | None
    hosts: tuple[str, ...]
    host_suffixes: tuple[str, ...]

    @classmethod
    def from_view(cls, value: ProviderStatusView) -> ProviderStatusResponse:
        return cls(
            key=value.key,
            display_name=value.display_name,
            registered=value.registered,
            extractor_exists=value.extractor_exists,
            capabilities=value.capabilities,
            identity=value.identity,
            status=value.status,
            download_supported=value.download_supported,
            user_action=value.user_action,
            hosts=value.hosts,
            host_suffixes=value.host_suffixes,
        )


class ProviderListResponse(StrictModel):
    items: tuple[ProviderStatusResponse, ...]

    @classmethod
    def from_views(cls, values: tuple[ProviderStatusView, ...]) -> ProviderListResponse:
        return cls(
            items=tuple(ProviderStatusResponse.from_view(item) for item in values)
        )
