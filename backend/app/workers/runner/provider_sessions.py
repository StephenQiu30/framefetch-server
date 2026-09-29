"""Access context and per-operation Cookie jars for anonymous and site-session
runners."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from app.integrations.site_session_catalog import known_site_policy, site_target_for_url
from app.services.provider_types import (
    ProviderAccessContextRef,
    ProviderAccessMode,
    ProviderKey,
)
from app.services.site_sessions import InvalidSessionSite
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_credential_lease import ProviderCredentialLocks
from app.workers.runner.provider_registry import (
    ProviderProfile,
    provider_profile_for_key,
)
from app.workers.runner.provider_session_files import (
    operation_cookie,
    prepare_private_root,
    require_memory_backed_root,
)
from app.workers.runner.release_identity import runtime_code_sha256
from app.workers.runner.settings import RunnerSettings
from app.workers.runner.site_sessions import (
    SiteSessionClient,
    context_version,
    parse_context_version,
)

# A sibling operation on the same site is queued, not failed.
_SESSION_LOCK_WAIT_SECONDS = 30.0


class ProviderSessionStore:
    """Freeze an access context, then hand out one tmpfs Cookie jar per operation."""

    def __init__(
        self,
        settings: RunnerSettings,
        *,
        credential_locks: ProviderCredentialLocks | None = None,
        site_sessions: SiteSessionClient | None = None,
        enforce_memory_backing: bool = True,
    ) -> None:
        self._settings = settings
        self._temp_root = settings.runner_provider_session_temp_root
        self._credential_locks = credential_locks or ProviderCredentialLocks()
        self._site_sessions = site_sessions
        broker, secret = (
            settings.runner_session_broker_url,
            settings.runner_session_rpc_secret,
        )
        if self._site_sessions is None and broker and secret is not None:
            self._site_sessions = SiteSessionClient(
                broker, secret.get_secret_value().encode()
            )
        if settings.runner_access_mode is not ProviderAccessMode.ANONYMOUS:
            prepare_private_root(self._temp_root)
            if enforce_memory_backing:
                require_memory_backed_root(self._temp_root)

    async def context_for(
        self, profile: ProviderProfile, *, url: str | None = None
    ) -> ProviderAccessContextRef:
        mode = self._settings.runner_access_mode
        if mode is ProviderAccessMode.OPERATOR_MANAGED:
            mode = profile.execution_access_mode
        credential_version: str | None = None
        if mode is ProviderAccessMode.OPERATOR_MANAGED:
            # Any site with a deployment session is admitted by the broker, not
            # by the provider catalog: that is how unlisted sites work too.
            site = self._site_for(profile, url)
            assert self._site_sessions is not None
            revision = await self._site_sessions.ready_revision(site)
            credential_version = context_version(site, revision)
        elif mode not in profile.access_modes:
            raise RunnerFailure("provider_session_not_allowed", status=422)
        return ProviderAccessContextRef(
            provider_key=profile.key,
            profile_version=profile.version,
            access_mode=mode,
            credential_version_id=credential_version,
            egress_affinity_id=self._settings.egress_affinity_for(profile.key),
            client_profile_id=profile.client_profile_id,
            attestation_provider_version=(
                self._settings.runner_youtube_pot_provider_version
                if profile.key == ProviderKey.YOUTUBE
                and self._settings.runner_youtube_pot_base_url is not None
                else None
            ),
            engine_commit=self._settings.runner_ytdlp_commit,
            runtime_revision=runtime_code_sha256(profile.key, access_mode=mode),
        )

    async def validate_context(
        self,
        profile: ProviderProfile,
        expected: ProviderAccessContextRef,
        *,
        url: str | None = None,
    ) -> ProviderAccessContextRef:
        current = await self.context_for(profile, url=url)
        if (
            expected.runtime_revision != current.runtime_revision
            and replace(expected, runtime_revision=current.runtime_revision) == current
        ):
            raise RunnerFailure("runner_release_changed", status=409)
        if current.access_mode is ProviderAccessMode.ANONYMOUS:
            if current != expected:
                raise RunnerFailure("client_context_mismatch", status=409)
            return current
        if expected != current:
            # A re-import changes the frozen revision: the inspection is stale.
            raise RunnerFailure("credential_revoked", status=422)
        return current

    @asynccontextmanager
    async def operation(
        self, context: ProviderAccessContextRef
    ) -> AsyncIterator[Path | None]:
        if (
            self._settings.runner_access_mode is ProviderAccessMode.OPERATOR_MANAGED
            and context.access_mode
            is not provider_profile_for_key(context.provider_key).execution_access_mode
        ):
            raise RunnerFailure("provider_session_not_allowed", status=422)
        if context.access_mode is ProviderAccessMode.ANONYMOUS:
            yield None
            return
        site, revision = parse_context_version(context.credential_version_id)
        assert self._site_sessions is not None
        # One operation per site identity at a time.
        async with self._credential_locks.hold(
            site, "session", wait_seconds=_SESSION_LOCK_WAIT_SECONDS
        ):
            payload = await self._site_sessions.lease(site, revision)
            with operation_cookie(
                payload, self._temp_root, context.provider_key
            ) as jar:
                yield jar

    def _site_for(self, profile: ProviderProfile, url: str | None) -> str:
        try:
            if url is not None:
                return site_target_for_url(url).site
        except InvalidSessionSite as exc:
            raise RunnerFailure("provider_session_not_allowed", status=422) from exc
        policy = known_site_policy(profile.key)
        if policy is None:
            raise RunnerFailure("provider_session_not_allowed", status=422)
        return policy.site

    async def close(self) -> None:
        if self._site_sessions is not None:
            await self._site_sessions.close()
