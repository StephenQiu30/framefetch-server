"""Map URLs to deployment site sessions using the provider registry's hosts."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from app.services.downloads.errors import (
    MediaInspectionPolicyNotAllowed,
)
from app.services.provider_access import ProviderAccessPolicy
from app.services.site_sessions import (
    InvalidSessionSite,
    SiteSessionPolicy,
    registrable_site,
)
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import (
    current_provider_registry,
    provider_profile,
    provider_profile_for_key,
)


def known_site_policy(provider_key: str) -> SiteSessionPolicy | None:
    return next(
        (
            policy
            for policy in current_provider_registry().session_policies
            if policy.provider_key == provider_key
        ),
        None,
    )


def known_session_provider_keys() -> frozenset[str]:
    return frozenset(
        policy.provider_key
        for policy in current_provider_registry().session_policies
        if policy.provider_key is not None
    )


def known_session_sites() -> tuple[str, ...]:
    return tuple(policy.site for policy in current_provider_registry().session_policies)


def site_policy(site: str) -> SiteSessionPolicy:
    for policy in current_provider_registry().session_policies:
        if policy.site == site:
            return policy
    if registrable_site(site) != site:
        raise InvalidSessionSite(
            "unknown session sites are keyed by registrable domain"
        )
    return SiteSessionPolicy(site, None, f"https://{site}/")


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


class SiteSessionRoutes:
    """Apply the profile's approved strategy before any session or media I/O."""

    async def policy_for(self, url: str) -> ProviderAccessPolicy:
        try:
            profile = provider_profile(url)
            # Resolving a host classifies it; execution also checks retirement.
            provider_profile_for_key(profile.key)
            if profile.access_policy is ProviderAccessPolicy.PUBLIC:
                return profile.access_policy
            target = site_target_for_url(url)
        except (InvalidSessionSite, RunnerFailure) as exc:
            raise MediaInspectionPolicyNotAllowed from exc
        if target.policy.provider_key is None:
            raise MediaInspectionPolicyNotAllowed
        return profile.access_policy

    async def ensure_ready(self, url: str) -> None:
        """Login state lives in the dedicated platform browser and is read per operation
        by the Runner, so there is no stored state to gate on here."""
        if await self.policy_for(url) is ProviderAccessPolicy.PUBLIC:
            return
        site_target_for_url(url)
