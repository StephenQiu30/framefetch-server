"""Strategy and registry primitives for media providers."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import SplitResult, urlsplit

from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_types import (
    ProviderAccessMode,
    ProviderCapability,
    ProviderProfileVersion,
    ProviderSupportStatus,
)
from app.services.site_sessions import SessionEntitlement, SiteSessionPolicy
from app.workers.runner.errors import RunnerFailure

UNSUPPORTED_PROVIDER_DOMAINS = frozenset(
    {
        "acfun.cn",
        "rutube.ru",
        "vk.com",
        "vk.ru",
        "vkvideo.ru",
        "dailymotion.com",
        "dai.ly",
        "nicovideo.jp",
        "nico.ms",
    }
)

UrlNormalizer = Callable[[str, SplitResult], str]


class ProviderRuntimeSettings(Protocol):
    runner_youtube_pot_base_url: str | None


RuntimeCommandArgs = Callable[[ProviderRuntimeSettings], tuple[str, ...]]


def identity_url(url: str, _parsed: SplitResult) -> str:
    return url


def default_runtime_command_args(
    _settings: ProviderRuntimeSettings,
) -> tuple[str, ...]:
    return ()


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    key: str
    display_name: str
    hosts: frozenset[str]
    host_suffixes: frozenset[str] = frozenset()
    version: str = ProviderProfileVersion.DEFAULT
    capabilities: frozenset[ProviderCapability] = frozenset(
        {ProviderCapability.SINGLE_VIDEO}
    )
    access_modes: tuple[ProviderAccessMode, ...] = (ProviderAccessMode.ANONYMOUS,)
    # Engine support is not execution approval. All callers use this policy;
    # cookies, runtime failures and caller parameters cannot change it.
    access_policy: ProviderAccessPolicy = ProviderAccessPolicy.PUBLIC
    session_policy: SiteSessionPolicy | None = None
    cookie_domain_allowlist: frozenset[str] = frozenset()
    client_profile_id: str = "yt-dlp-default"
    attestation_policy: str = "none"
    egress_pool: str = "default"
    credential_concurrency: int = 0
    support_status: ProviderSupportStatus = ProviderSupportStatus.UNKNOWN
    canary_suite: str = "anonymous-metadata-range"
    error_policy_id: str = "yt-dlp-stable-v2"
    command_args: tuple[str, ...] = ()
    runtime_command_args: RuntimeCommandArgs = default_runtime_command_args
    yt_dlp_retry_count: int = 3
    inspection_attempts: int = 2
    inspection_retry_delay: float = 1.0
    probe_authenticated_media: bool = False
    probe_media_duration: bool = False
    normalize_url: UrlNormalizer = identity_url

    @property
    def execution_access_mode(self) -> ProviderAccessMode:
        return self.access_policy.access_mode

    def request_url(self, url: str, parsed: SplitResult) -> str:
        return self.normalize_url(url, parsed)

    def command_args_for(self, settings: ProviderRuntimeSettings) -> tuple[str, ...]:
        return (*self.command_args, *self.runtime_command_args(settings))


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """One resolved provider strategy reused throughout an operation."""

    source_url: str
    request_url: str
    profile: ProviderProfile


class ProviderRegistry:
    """Registry/Factory for matching a URL to an approved strategy."""

    def __init__(
        self,
        profiles: Iterable[ProviderProfile],
        *,
        fallback: ProviderProfile | None = None,
    ) -> None:
        configured = tuple(profiles)
        by_host: dict[str, ProviderProfile] = {}
        by_host_suffix: dict[str, ProviderProfile] = {}
        by_site: dict[str, SiteSessionPolicy] = {}
        keys: set[str] = set()
        for profile in configured:
            if profile.key in keys:
                raise ValueError(f"provider key is registered twice: {profile.key}")
            keys.add(profile.key)
            if not profile.hosts:
                raise ValueError(f"provider {profile.key} must declare hosts")
            if (
                profile.yt_dlp_retry_count < 0
                or profile.inspection_attempts < 1
                or profile.inspection_retry_delay < 0
            ):
                raise ValueError(f"provider {profile.key} has invalid retry policy")
            if (
                not profile.version
                or not profile.capabilities
                or not profile.access_modes
                or not profile.error_policy_id
                or not profile.canary_suite
            ):
                raise ValueError(f"provider {profile.key} has incomplete capabilities")
            if (
                profile.access_policy is ProviderAccessPolicy.PUBLIC_SESSION
                or profile.execution_access_mode not in profile.access_modes
            ):
                raise ValueError(f"provider {profile.key} has invalid access policy")
            supports_operator = (
                ProviderAccessMode.OPERATOR_MANAGED in profile.access_modes
            )
            if supports_operator != bool(profile.cookie_domain_allowlist):
                raise ValueError(f"provider {profile.key} has invalid session policy")
            if supports_operator != (profile.credential_concurrency > 0):
                raise ValueError(f"provider {profile.key} has invalid session limit")
            session = profile.session_policy
            if supports_operator != (session is not None):
                raise ValueError(f"provider {profile.key} has missing session policy")
            if session is not None:
                if session.provider_key != profile.key:
                    raise ValueError(f"provider {profile.key} has mismatched session")
                if session.site in by_site:
                    raise ValueError(
                        f"provider session site is registered twice: {session.site}"
                    )
                personal = (
                    profile.access_policy is ProviderAccessPolicy.PERSONAL_ENTITLED
                )
                if personal != (
                    session.entitlement
                    is SessionEntitlement.ACCOUNT_ENTITLED_FULL_VIDEO
                ):
                    raise ValueError(
                        f"provider {profile.key} has mismatched entitlement"
                    )
                by_site[session.site] = session
            if profile.probe_authenticated_media and not supports_operator:
                raise ValueError(
                    f"provider {profile.key} cannot probe authenticated media"
                )
            for host in profile.hosts:
                if host in by_host:
                    raise ValueError(f"provider host is registered twice: {host}")
                by_host[host] = profile
            for suffix in profile.host_suffixes:
                if suffix in by_host_suffix:
                    raise ValueError(
                        f"provider host suffix is registered twice: {suffix}"
                    )
                by_host_suffix[suffix] = profile
        self._profiles = configured
        self._by_key = {profile.key: profile for profile in configured}
        self._by_host = by_host
        self._by_host_suffix = by_host_suffix
        self._by_site = by_site
        self._fallback = fallback or ProviderProfile(
            "generic",
            "Generic media source",
            frozenset(),
            access_policy=ProviderAccessPolicy.OPERATOR_PUBLIC,
            support_status=ProviderSupportStatus.UNKNOWN,
            canary_suite="generic-public-fixtures",
        )

    @property
    def profiles(self) -> tuple[ProviderProfile, ...]:
        return self._profiles

    def keys_for_policy(self, policy: ProviderAccessPolicy) -> frozenset[str]:
        return frozenset(
            profile.key
            for profile in self._profiles
            if profile.access_policy is policy
            and profile.support_status is not ProviderSupportStatus.DISABLED
        )

    @property
    def session_policies(self) -> tuple[SiteSessionPolicy, ...]:
        return tuple(self._by_site.values())

    def resolve(self, url: str) -> ProviderProfile:
        hostname = urlsplit(url).hostname
        if hostname is not None and any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in UNSUPPORTED_PROVIDER_DOMAINS
        ):
            raise RunnerFailure("provider_unsupported", status=422)
        if hostname is None:
            return self._fallback
        exact = self._by_host.get(hostname)
        if exact is not None:
            return exact
        suffix_matches = (
            (suffix, profile)
            for suffix, profile in self._by_host_suffix.items()
            if hostname.endswith(f".{suffix}")
        )
        return max(
            suffix_matches,
            key=lambda item: len(item[0]),
            default=("", self._fallback),
        )[1]

    def profile_for_key(self, provider_key: str) -> ProviderProfile:
        profile = self._by_key.get(provider_key)
        if profile is None and provider_key == self._fallback.key:
            profile = self._fallback
        if profile is None or profile.support_status is ProviderSupportStatus.DISABLED:
            raise RunnerFailure("provider_unsupported", status=422)
        return profile

    def prepare(self, url: str) -> ProviderRequest:
        profile = self.resolve(url)
        if profile.support_status is ProviderSupportStatus.DISABLED:
            raise RunnerFailure("provider_unsupported", status=422)
        return ProviderRequest(
            source_url=url,
            request_url=profile.request_url(url, urlsplit(url)),
            profile=profile,
        )


_DEFAULT_PROVIDER_REGISTRY: ProviderRegistry | None = None
_ACTIVE_PROVIDER_REGISTRY: ProviderRegistry | None = None


def default_provider_registry() -> ProviderRegistry:
    global _DEFAULT_PROVIDER_REGISTRY
    if _DEFAULT_PROVIDER_REGISTRY is None:
        from app.workers.runner.provider_catalog import DEFAULT_PROVIDER_PROFILES

        _DEFAULT_PROVIDER_REGISTRY = ProviderRegistry(DEFAULT_PROVIDER_PROFILES)
    return _DEFAULT_PROVIDER_REGISTRY


def configure_provider_instances(peertube_hosts: frozenset[str]) -> None:
    """Replace the process-local registry during startup only."""
    global _ACTIVE_PROVIDER_REGISTRY
    if not peertube_hosts:
        _ACTIVE_PROVIDER_REGISTRY = None
        return
    from app.workers.runner.provider_catalog_incremental import peertube_profile
    from app.workers.runner.provider_instances import validated_instance_hosts

    profile = peertube_profile(validated_instance_hosts(peertube_hosts))
    _ACTIVE_PROVIDER_REGISTRY = ProviderRegistry(
        (*default_provider_registry().profiles, profile)
    )


def current_provider_registry() -> ProviderRegistry:
    return _ACTIVE_PROVIDER_REGISTRY or default_provider_registry()


def provider_profile(url: str) -> ProviderProfile:
    return current_provider_registry().resolve(url)


def provider_profile_for_key(provider_key: str) -> ProviderProfile:
    return current_provider_registry().profile_for_key(provider_key)


def provider_request(url: str) -> ProviderRequest:
    return current_provider_registry().prepare(url)
