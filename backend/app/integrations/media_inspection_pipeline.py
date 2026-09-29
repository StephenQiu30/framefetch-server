"""Online media uses exactly one deployment-owned session route."""

from __future__ import annotations

from typing import Protocol

from app.services.downloads.errors import (
    MediaInspectionFailure,
    MediaInspectionPolicyNotAllowed,
)
from app.services.downloads.inspection_models import RunnerInspection
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_types import ProviderAccessMode
from app.workers.runner.provider_registry import provider_profile


class MediaInspectionClient(Protocol):
    async def inspect(self, url: str) -> RunnerInspection: ...


class SessionPolicyReader(Protocol):
    async def policy_for(self, url: str) -> ProviderAccessPolicy: ...
    async def ensure_ready(self, url: str) -> None: ...


class MediaInspectionPipeline:
    def __init__(
        self, session: MediaInspectionClient, *, session_routes: SessionPolicyReader
    ) -> None:
        self._session = session
        self._session_routes = session_routes

    async def resolve_access_policy(
        self, url: str, requested: ProviderAccessPolicy | None = None
    ) -> ProviderAccessPolicy:
        selected = await self._session_routes.policy_for(url)
        if requested not in {None, selected}:
            raise MediaInspectionPolicyNotAllowed
        return selected

    async def inspect(
        self, url: str, *, access_policy: ProviderAccessPolicy | None = None
    ) -> RunnerInspection:
        selected = await self.resolve_access_policy(url, access_policy)
        try:
            await self._session_routes.ensure_ready(url)
            result = await self._session.inspect(url)
            profile = provider_profile(url)
            allowed_modes = {selected.access_mode}
            if (
                selected is ProviderAccessPolicy.OPERATOR_PUBLIC
                and ProviderAccessMode.ANONYMOUS in profile.access_modes
            ):
                allowed_modes.add(ProviderAccessMode.ANONYMOUS)
            if (
                result.access_context.access_mode not in allowed_modes
                or result.access_context.provider_key != profile.key
            ):
                raise MediaInspectionFailure("runner policy context mismatch")
            return result
        except MediaInspectionFailure as error:
            error.attributed_to(selected.access_mode)
            raise
