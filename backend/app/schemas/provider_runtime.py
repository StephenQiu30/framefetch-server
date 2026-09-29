"""Allowlisted admin diagnostics, never a serialized access context."""

from datetime import datetime
from typing import Literal

from app.schemas.common import StrictModel
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_types import ProviderAccessMode
from app.services.providers import ProviderEvidenceState, ProviderStatusView
from app.services.site_sessions import known_site_policy


class ProviderRuntimeResponse(StrictModel):
    # Live: whether the Runner could read this site's login from local Chrome.
    login_state: Literal["not_required", "signed_in", "unavailable"]
    session_site: str | None = None
    provider_key: str
    access_policy_id: ProviderAccessPolicy | None
    route_configured: bool
    context_available: bool
    profile_version: str | None
    engine_commit: str | None
    source_state: Literal[
        "not_required", "revision_observed", "not_observed", "unknown"
    ]
    evidence_state: ProviderEvidenceState
    last_media_verified_at: datetime | None
    user_action: str | None
    route_retry_at: datetime | None = None

    @classmethod
    def from_view(cls, view: ProviderStatusView) -> "ProviderRuntimeResponse":
        site_policy = known_site_policy(view.key)
        context = view.runtime_context
        policy = view.default_access_policy_id
        return cls(
            provider_key=view.key,
            login_state=(
                "not_required"
                if policy is None or policy.access_mode is ProviderAccessMode.ANONYMOUS
                else "signed_in"
                if context is not None
                else "unavailable"
            ),
            session_site=site_policy.site if site_policy else None,
            access_policy_id=policy,
            route_configured=any(
                item.id is policy and item.configured for item in view.access_policies
            ),
            context_available=context is not None,
            profile_version=context.profile_version
            if context is not None
            else view.profile_version,
            engine_commit=context.engine_commit if context is not None else None,
            source_state=(
                "unknown"
                if policy is None
                else "not_required"
                if policy.access_mode is ProviderAccessMode.ANONYMOUS
                else "revision_observed"
                if context is not None and context.credential_version_id
                else "not_observed"
            ),
            evidence_state=view.evidence_state,
            last_media_verified_at=view.last_media_verified_at,
            user_action=view.user_action,
            route_retry_at=view.route_retry_at,
        )


class ProviderRuntimeListResponse(StrictModel):
    items: tuple[ProviderRuntimeResponse, ...]
    snapshot_max_age_seconds: int = 30
