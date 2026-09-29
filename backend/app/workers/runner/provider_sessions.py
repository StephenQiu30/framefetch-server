"""Access context and per-operation Cookie jars for anonymous, guest and site
session runners."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app.integrations.site_session_catalog import site_target_for_url
from app.services.provider_access import execution_access_mode
from app.services.provider_guest import GuestScope
from app.services.provider_types import (
    ProviderAccessContextRef,
    ProviderAccessMode,
    ProviderKey,
)
from app.services.site_sessions import InvalidSessionSite, known_site_policy
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.guest_material import read_guest_lease
from app.workers.runner.provider_credential_lease import (
    ProviderCredentialLeaseCoordinator,
)
from app.workers.runner.provider_registry import ProviderProfile
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

# A keepalive or sibling operation on the same site is queued, not failed.
_SESSION_LOCK_WAIT_SECONDS = 30.0


class ProviderSessionStore:
    """Freeze an access context, then hand out one tmpfs Cookie jar per operation."""

    def __init__(
        self,
        settings: RunnerSettings,
        *,
        credential_lease: ProviderCredentialLeaseCoordinator | None = None,
        site_sessions: SiteSessionClient | None = None,
        enforce_memory_backing: bool = True,
    ) -> None:
        self._settings = settings
        self._temp_root = settings.runner_provider_session_temp_root
        self._gate = asyncio.Semaphore(1)
        self._credential_lease = credential_lease
        if (
            self._credential_lease is None
            and settings.runner_credential_lease_redis_url
        ):
            self._credential_lease = ProviderCredentialLeaseCoordinator(
                settings.runner_credential_lease_redis_url,
                ttl_seconds=settings.runner_credential_lease_ttl_seconds,
                heartbeat_seconds=settings.runner_credential_lease_heartbeat_seconds,
            )
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

    async def is_ready(self) -> bool:
        mode = self._settings.runner_access_mode
        if mode is ProviderAccessMode.ANONYMOUS:
            return True
        try:
            if mode is ProviderAccessMode.GUEST:
                provider = self._settings.runner_guest_provider
                assert provider is not None
                self._guest_version(_profile_for_key(provider))
            assert self._credential_lease is not None
            await self._credential_lease.ping()
        except RunnerFailure:
            return False
        return True

    async def context_for(
        self, profile: ProviderProfile, *, url: str | None = None
    ) -> ProviderAccessContextRef:
        mode = self._settings.runner_access_mode
        if mode is ProviderAccessMode.OPERATOR_MANAGED:
            mode = execution_access_mode(profile.key)
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
        elif mode is ProviderAccessMode.GUEST:
            credential_version = self._guest_version(profile)
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
        allow_guest_refresh: bool = False,
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
            if (
                allow_guest_refresh
                and current.access_mode is ProviderAccessMode.GUEST
                and expected.access_mode is ProviderAccessMode.GUEST
                and replace(
                    expected, credential_version_id=current.credential_version_id
                )
                == current
            ):
                # Only visitor material may rotate. Provider, engine, profile,
                # client and egress remain frozen; download re-inspects identity.
                return current
            if current.access_mode is ProviderAccessMode.GUEST:
                raise RunnerFailure("guest_context_required", status=503)
            # A re-import changes the frozen revision: the inspection is stale.
            raise RunnerFailure("credential_revoked", status=422)
        return current

    @asynccontextmanager
    async def operation(
        self, context: ProviderAccessContextRef
    ) -> AsyncIterator[Path | None]:
        if (
            self._settings.runner_access_mode is ProviderAccessMode.OPERATOR_MANAGED
            and context.access_mode is not execution_access_mode(context.provider_key)
        ):
            raise RunnerFailure("provider_session_not_allowed", status=422)
        if context.access_mode is ProviderAccessMode.ANONYMOUS:
            yield None
            return
        assert self._credential_lease is not None
        if context.access_mode is ProviderAccessMode.GUEST:
            profile = _profile_for_key(context.provider_key)
            path = self._settings.runner_guest_cookie_file
            if (
                path is None
                or context.provider_key != self._settings.runner_guest_provider
            ):
                raise RunnerFailure("provider_session_not_allowed", status=422)
            async with (
                self._gate,
                self._credential_lease.hold(context.provider_key, "public-guest"),
            ):
                lease = read_guest_lease(
                    path, self._guest_scope(profile), now=datetime.now(UTC)
                )
                if lease.version != context.credential_version_id:
                    raise RunnerFailure("guest_context_required", status=503)
                with operation_cookie(
                    lease.payload, self._temp_root, context.provider_key
                ) as jar:
                    yield jar
            return
        site, revision = parse_context_version(context.credential_version_id)
        assert self._site_sessions is not None
        # One operation per site identity across every Runner replica.
        async with self._credential_lease.hold(
            site, "session", wait_seconds=_SESSION_LOCK_WAIT_SECONDS
        ):
            operation = await self._site_sessions.lease(site, revision)
            with operation_cookie(
                operation.payload, self._temp_root, context.provider_key
            ) as jar:
                yield jar
                if jar.stat().st_size > 2_000_000:
                    raise RunnerFailure("provider_session_unavailable", status=503)
                await self._site_sessions.rotate(operation, jar.read_bytes())

    async def report_failure(
        self, context: ProviderAccessContextRef, error_code: str
    ) -> None:
        if context.access_mode is not ProviderAccessMode.OPERATOR_MANAGED:
            return
        if self._site_sessions is None:
            return
        try:
            site, revision = parse_context_version(context.credential_version_id)
        except RunnerFailure:
            return
        await self._site_sessions.report(site, revision, error_code)

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

    def _guest_version(self, profile: ProviderProfile) -> str:
        if profile.key != self._settings.runner_guest_provider:
            raise RunnerFailure("provider_session_not_allowed", status=422)
        path = self._settings.runner_guest_cookie_file
        assert path is not None
        return read_guest_lease(
            path, self._guest_scope(profile), now=datetime.now(UTC)
        ).version

    def _guest_scope(self, profile: ProviderProfile) -> GuestScope:
        return GuestScope(
            ProviderKey(profile.key),
            profile.version,
            profile.client_profile_id,
            self._settings.egress_affinity_for(profile.key),
        )

    async def close(self) -> None:
        try:
            if self._site_sessions is not None:
                await self._site_sessions.close()
        finally:
            if self._credential_lease is not None:
                await self._credential_lease.close()


def _profile_for_key(key: str | ProviderKey) -> ProviderProfile:
    from app.workers.runner.provider_registry import default_provider_registry

    for profile in default_provider_registry().profiles:
        if profile.key == key:
            return profile
    raise RunnerFailure("provider_session_not_allowed", status=422)
