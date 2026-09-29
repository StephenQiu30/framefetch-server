"""Map URLs to deployment site sessions using the provider registry's hosts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from app.services.downloads.errors import (
    MediaInspectionConfigurationMissing,
    MediaInspectionPolicyNotAllowed,
    MediaInspectionSessionNotReady,
)
from app.services.provider_access import NATIVE_PUBLIC_PROVIDERS, ProviderAccessPolicy
from app.services.site_sessions import (
    InvalidSessionSite,
    SessionEntitlement,
    SiteSessionPolicy,
    SiteSessionState,
    SiteSessionStatus,
    known_site_policy,
    registrable_site,
    site_policy,
)
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import (
    provider_profile,
    provider_profile_for_key,
)


@dataclass(frozen=True, slots=True)
class SiteTarget:
    policy: SiteSessionPolicy
    cookie_domains: frozenset[str]

    @property
    def site(self) -> str:
        return self.policy.site


def site_target_for_url(url: str) -> SiteTarget:
    """Known provider hosts win; any other host is scoped by registrable domain."""
    profile = provider_profile(url)
    known = known_site_policy(profile.key)
    if known is not None:
        return _target(known)
    host = urlsplit(url).hostname
    if host is None:
        raise InvalidSessionSite("URL has no host")
    return _target(site_policy(registrable_site(host)))


def site_target_for_host(host: str) -> SiteTarget:
    """Resolve an operator-supplied host or site key, e.g. ``youtu.be``."""
    normalized = host.strip().lower().rstrip(".")
    registrable_site(normalized)  # rejects IPs, paths, private and suffix-only names
    return site_target_for_url(f"https://{normalized}/")


def site_target(site: str) -> SiteTarget:
    """Resolve a stored site key without reinterpreting it as a URL."""
    return _target(site_policy(site))


def _target(policy: SiteSessionPolicy) -> SiteTarget:
    if policy.provider_key is None:
        return SiteTarget(policy, frozenset({policy.site}))
    domains = provider_profile_for_key(policy.provider_key).cookie_domain_allowlist
    if not domains:
        raise InvalidSessionSite("provider has no session cookie domains")
    return SiteTarget(policy, frozenset(str(domain) for domain in domains))


class SiteSessionStatusReader(Protocol):
    async def get(self, site: str) -> SiteSessionStatus | None: ...


class SiteSessionRoutes:
    """Decide from persisted state whether a URL must use its site session."""

    def __init__(self, states: SiteSessionStatusReader) -> None:
        self._states = states

    async def policy_for(self, url: str) -> ProviderAccessPolicy:
        if provider_profile(url).key in NATIVE_PUBLIC_PROVIDERS:
            return ProviderAccessPolicy.PUBLIC
        try:
            target = site_target_for_url(url)
        except (InvalidSessionSite, RunnerFailure) as exc:
            raise MediaInspectionPolicyNotAllowed from exc
        if target.policy.provider_key is None:
            raise MediaInspectionPolicyNotAllowed
        if target.policy.entitlement is SessionEntitlement.ACCOUNT_ENTITLED_FULL_VIDEO:
            return ProviderAccessPolicy.PERSONAL_ENTITLED
        return ProviderAccessPolicy.OPERATOR_PUBLIC

    async def ensure_ready(self, url: str) -> None:
        if provider_profile(url).key in NATIVE_PUBLIC_PROVIDERS:
            return
        target = site_target_for_url(url)
        status = await self._states.get(target.site)
        if status is None or status.state in {
            SiteSessionState.REVOKED,
            SiteSessionState.RESEED_REQUIRED,
        }:
            raise MediaInspectionConfigurationMissing
        if status.state is not SiteSessionState.READY:
            raise MediaInspectionSessionNotReady(before_media_io=True)
