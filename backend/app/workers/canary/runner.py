"""Explicit access-route selection for Provider canaries."""

from __future__ import annotations

from collections.abc import Mapping

from app.integrations.media_runner import MediaRunnerClient
from app.integrations.media_runner_models import MediaRunnerClientError, RunnerArtifact
from app.services.downloads.errors import (
    MediaInspectionAuthRequired,
    MediaInspectionFailure,
    MediaInspectionGuestContextRequired,
)
from app.services.downloads.inspection_models import RunnerInspection
from app.services.downloads.rules.enums import MediaKind
from app.services.downloads.rules.formats import DownloadPlan
from app.services.provider_types import ProviderAccessContextRef, ProviderAccessMode
from app.workers.runner.provider_registry import provider_profile


class ProviderCanaryRunner:
    """Run exactly one declared route without business download fallback."""

    def __init__(
        self,
        anonymous: MediaRunnerClient,
        session: MediaRunnerClient | None = None,
        *,
        guests: Mapping[str, MediaRunnerClient] | None = None,
    ) -> None:
        self._anonymous = anonymous
        self._session = session
        self._guests = dict(guests or {})

    async def context(
        self,
        url: str,
        *,
        access_mode: ProviderAccessMode,
    ) -> ProviderAccessContextRef:
        profile = provider_profile(url)
        if access_mode not in profile.access_modes:
            raise MediaInspectionAuthRequired(access_mode=access_mode)
        client = self._inspection_client(profile.key, access_mode)
        return await client.context(url)

    async def inspect(
        self,
        url: str,
        *,
        access_mode: ProviderAccessMode,
    ) -> RunnerInspection:
        profile = provider_profile(url)
        if access_mode not in profile.access_modes:
            raise MediaInspectionAuthRequired(access_mode=access_mode)
        client = self._inspection_client(profile.key, access_mode)
        try:
            return await client.inspect(url)
        except MediaInspectionFailure as error:
            error.attributed_to(access_mode)
            raise

    async def download(
        self,
        task_id: str,
        url: str,
        plan: DownloadPlan | None,
        *,
        expected_provider_media_id: str,
        expected_extractor_key: str,
        access_context: ProviderAccessContextRef,
        media_kind: MediaKind = MediaKind.VIDEO,
    ) -> RunnerArtifact:
        client = self._client_for_context(access_context)
        return await client.download(
            task_id,
            url,
            plan,
            expected_provider_media_id=expected_provider_media_id,
            expected_extractor_key=expected_extractor_key,
            access_context=access_context,
            media_kind=media_kind,
        )

    async def close(self) -> None:
        await self._anonymous.close()
        if self._session is not None:
            await self._session.close()
        for client in self._guests.values():
            await client.close()

    def _inspection_client(
        self,
        provider_key: str,
        access_mode: ProviderAccessMode,
    ) -> MediaRunnerClient:
        if access_mode is ProviderAccessMode.ANONYMOUS:
            return self._anonymous
        if access_mode is ProviderAccessMode.GUEST:
            guest = self._guests.get(provider_key)
            if guest is None:
                raise MediaInspectionGuestContextRequired(access_mode=access_mode)
            return guest
        if self._session is None:
            raise MediaInspectionAuthRequired(access_mode=access_mode)
        return self._session

    def _client_for_context(
        self, context: ProviderAccessContextRef
    ) -> MediaRunnerClient:
        if context.access_mode is ProviderAccessMode.ANONYMOUS:
            return self._anonymous
        if context.access_mode is ProviderAccessMode.GUEST:
            guest = self._guests.get(context.provider_key)
            if guest is None:
                raise MediaRunnerClientError("guest_context_required", 503)
            return guest
        if self._session is None:
            raise MediaRunnerClientError("credential_required", 422)
        return self._session
