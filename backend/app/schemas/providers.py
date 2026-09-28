from __future__ import annotations

from datetime import datetime

from app.schemas.common import StrictModel
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_types import (
    ProviderAccessMode,
    ProviderAccessState,
    ProviderCapability,
    ProviderSupportStatus,
)
from app.services.providers import ProviderEvidenceState, ProviderStatusView


class ProviderAccessPolicyResponse(StrictModel):
    id: ProviderAccessPolicy
    configured: bool


class ProviderStatusResponse(StrictModel):
    key: str
    display_name: str
    registered: bool
    extractor_exists: bool
    capabilities: tuple[ProviderCapability, ...]
    access_modes: tuple[ProviderAccessMode, ...]
    access_state: ProviderAccessState
    status: ProviderSupportStatus
    last_checked_at: datetime | None
    last_check_succeeded: bool | None
    download_supported: bool
    download_available: bool
    last_media_verified_at: datetime | None
    last_verified_at: datetime | None
    user_action: str | None
    access_policies: tuple[ProviderAccessPolicyResponse, ...]
    default_access_policy_id: ProviderAccessPolicy | None
    evidence_state: ProviderEvidenceState
    hosts: tuple[str, ...]
    host_suffixes: tuple[str, ...]
    route_retry_at: datetime | None = None

    @classmethod
    def from_view(cls, value: ProviderStatusView) -> ProviderStatusResponse:
        return cls(
            key=value.key,
            display_name=value.display_name,
            registered=value.registered,
            extractor_exists=value.extractor_exists,
            capabilities=value.capabilities,
            access_modes=value.access_modes,
            access_state=value.access_state,
            status=value.status,
            last_checked_at=value.last_checked_at,
            last_check_succeeded=value.last_check_succeeded,
            download_supported=value.download_supported,
            download_available=value.download_available,
            last_media_verified_at=value.last_media_verified_at,
            last_verified_at=value.last_verified_at,
            user_action=value.user_action,
            access_policies=tuple(
                ProviderAccessPolicyResponse(id=item.id, configured=item.configured)
                for item in value.access_policies
            ),
            default_access_policy_id=value.default_access_policy_id,
            evidence_state=value.evidence_state,
            hosts=value.hosts,
            host_suffixes=value.host_suffixes,
            route_retry_at=value.route_retry_at,
        )


class ProviderListResponse(StrictModel):
    items: tuple[ProviderStatusResponse, ...]

    @classmethod
    def from_views(cls, values: tuple[ProviderStatusView, ...]) -> ProviderListResponse:
        return cls(
            items=tuple(ProviderStatusResponse.from_view(item) for item in values)
        )
