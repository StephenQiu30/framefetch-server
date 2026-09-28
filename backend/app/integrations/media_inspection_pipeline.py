"""Deterministic routing for media inspection.

A site with a deployment session record always uses the session Runner; there
is no anonymous fallback for it. Every other site keeps its public or guest
route.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from app.services.downloads.errors import (
    MediaInspectionConfigurationMissing,
    MediaInspectionFailure,
    MediaInspectionPolicyNotAllowed,
)
from app.services.downloads.inspection_models import RunnerInspection
from app.services.provider_access import (
    ProviderAccessPolicy,
    default_access_policy,
    provider_access_policies,
)
from app.services.provider_types import ProviderAccessMode
from app.workers.runner.provider_registry import provider_profile


class MediaInspectionClient(Protocol):
    """A concrete inspection strategy, such as an isolated runner pool."""

    async def inspect(self, url: str) -> RunnerInspection: ...


class SessionPolicyReader(Protocol):
    async def policy_for(self, url: str) -> ProviderAccessPolicy | None: ...


class MediaInspectionPipeline:
    """Route each URL to exactly one access mode for the whole operation."""

    def __init__(
        self,
        anonymous: MediaInspectionClient,
        session: MediaInspectionClient | None = None,
        *,
        guests: Mapping[str, MediaInspectionClient] | None = None,
        session_routes: SessionPolicyReader | None = None,
    ) -> None:
        self._anonymous = anonymous
        self._session = session
        self._guests = dict(guests or {})
        self._session_routes = session_routes

    async def resolve_access_policy(
        self, url: str, requested: ProviderAccessPolicy | None = None
    ) -> ProviderAccessPolicy:
        profile = provider_profile(url)
        forced = (
            None
            if self._session_routes is None
            else await self._session_routes.policy_for(url)
        )
        if forced is not None:
            if requested not in {None, forced}:
                raise MediaInspectionPolicyNotAllowed
            if self._session is None:
                raise MediaInspectionConfigurationMissing
            return forced
        selected = requested or default_access_policy(
            profile.key,
            profile.access_modes,
            guest_configured=profile.key in self._guests,
        )
        if selected not in provider_access_policies(profile.key, profile.access_modes):
            raise MediaInspectionPolicyNotAllowed
        if self._client_for(profile.key, selected.access_mode) is None:
            # Includes an account policy for a site without an imported session.
            raise MediaInspectionConfigurationMissing
        return selected

    async def inspect(
        self, url: str, *, access_policy: ProviderAccessPolicy | None = None
    ) -> RunnerInspection:
        selected = await self.resolve_access_policy(url, access_policy)
        profile = provider_profile(url)
        access_mode = selected.access_mode
        client = (
            self._session
            if access_mode is ProviderAccessMode.OPERATOR_MANAGED
            else self._client_for(profile.key, access_mode)
        )
        if client is None:
            raise MediaInspectionConfigurationMissing
        try:
            result = await client.inspect(url)
            if (
                result.access_context.access_mode is not access_mode
                or result.access_context.provider_key != profile.key
            ):
                raise MediaInspectionFailure("runner policy context mismatch")
            return result
        except MediaInspectionFailure as error:
            error.attributed_to(access_mode)
            raise

    def _client_for(
        self, provider_key: str, access_mode: ProviderAccessMode
    ) -> MediaInspectionClient | None:
        if access_mode is ProviderAccessMode.ANONYMOUS:
            return self._anonymous
        if access_mode is ProviderAccessMode.GUEST:
            return self._guests.get(provider_key)
        # The account mode is reachable only through a session record.
        return None
