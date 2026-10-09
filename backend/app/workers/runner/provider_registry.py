"""Strategy and registry primitives for media providers."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import SplitResult, urlsplit

from app.services.provider_types import (
    BrowserRules,
    EgressRoute,
    Layer,
    PrepareSpec,
    ProviderCapability,
    ProviderIdentity,
    ProviderKey,
    ProviderProfileVersion,
    ProviderSupportStatus,
)
from app.workers.identity.yuanbao_parse import YUANBAO_ORIGIN
from app.workers.runner.errors import RunnerFailure

UNSUPPORTED_PROVIDER_DOMAINS = frozenset(
    {
        "acfun.cn",
        "rutube.ru",
        "vk.com",
        "vk.ru",
        "vkvideo.ru",
        "nicovideo.jp",
        "nico.ms",
    }
)
_DAILYMOTION_DOMAINS = frozenset({"dailymotion.com", "dai.ly"})

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
    ladder: tuple[Layer, ...] = (Layer.L1,)
    egress_route: EgressRoute = EgressRoute.GLOBAL
    l2_prepare: PrepareSpec | None = None
    l3_rules: BrowserRules | None = None
    identity: ProviderIdentity = ProviderIdentity.NONE
    identity_source: Literal["cookies", "yuanbao_http"] = "cookies"
    identity_origin: str | None = None
    content_scope: Literal["public", "personal_full", "official_share"] = "public"
    cookie_domain_allowlist: frozenset[str] = frozenset()
    client_profile: str = "yt-dlp-default"
    support_status: ProviderSupportStatus = ProviderSupportStatus.UNKNOWN
    error_policy_id: str = "yt-dlp-stable"
    command_args: tuple[str, ...] = ()
    runtime_command_args: RuntimeCommandArgs = default_runtime_command_args
    yt_dlp_retry_count: int = 3
    probe_authenticated_media: bool = False
    probe_media_duration: bool = False
    normalize_url: UrlNormalizer = identity_url

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
        if fallback is not None and fallback.content_scope == "official_share":
            raise ValueError("fallback cannot use official share content scope")
        configured = tuple(profiles)
        by_host: dict[str, ProviderProfile] = {}
        by_host_suffix: dict[str, ProviderProfile] = {}
        keys: set[str] = set()
        for profile in configured:
            if profile.key in keys:
                raise ValueError(f"provider key is registered twice: {profile.key}")
            keys.add(profile.key)
            if not profile.hosts:
                raise ValueError(f"provider {profile.key} must declare hosts")
            if profile.content_scope not in {
                "public",
                "personal_full",
                "official_share",
            }:
                raise ValueError(f"provider {profile.key} has invalid content scope")
            if not profile.ladder or len(set(profile.ladder)) != len(profile.ladder):
                raise ValueError(f"provider {profile.key} has invalid ladder")
            if any(not isinstance(layer, Layer) for layer in profile.ladder):
                raise ValueError(f"provider {profile.key} has invalid layer")
            if not isinstance(profile.egress_route, EgressRoute):
                raise ValueError(f"provider {profile.key} has invalid egress route")
            if (Layer.L2 in profile.ladder) != (profile.l2_prepare is not None):
                raise ValueError(f"provider {profile.key} has invalid L2 preparation")
            if (Layer.L3 in profile.ladder) != (profile.l3_rules is not None):
                raise ValueError(f"provider {profile.key} has invalid L3 rules")
            if profile.l3_rules and profile.l3_rules.platform != profile.key:
                raise ValueError(f"provider {profile.key} has mismatched L3 rules")
            if profile.yt_dlp_retry_count < 0:
                raise ValueError(f"provider {profile.key} has invalid retry policy")
            if (
                not profile.version
                or not profile.capabilities
                or not profile.error_policy_id
            ):
                raise ValueError(f"provider {profile.key} has incomplete capabilities")
            if (
                profile.identity is ProviderIdentity.NONE
                and profile.cookie_domain_allowlist
            ):
                raise ValueError(
                    f"provider {profile.key} declares unused identity domains"
                )
            if profile.identity_source == "cookies":
                if profile.content_scope == "official_share":
                    raise ValueError(
                        f"provider {profile.key} has invalid "
                        "official share content scope"
                    )
                if profile.identity_origin is not None:
                    raise ValueError(
                        f"provider {profile.key} has invalid identity origin"
                    )
            elif profile.identity_source == "yuanbao_http":
                if (
                    profile.key != ProviderKey.WECHAT_CHANNELS
                    or profile.identity is not ProviderIdentity.REQUIRED
                    or profile.identity_origin != YUANBAO_ORIGIN
                    or profile.cookie_domain_allowlist
                    or profile.content_scope != "official_share"
                ):
                    raise ValueError(
                        f"provider {profile.key} has invalid page identity"
                    )
            else:
                raise ValueError(f"provider {profile.key} has invalid identity source")
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
        self._fallback = fallback or ProviderProfile(
            "generic",
            "Generic media source",
            frozenset(),
            support_status=ProviderSupportStatus.UNKNOWN,
            egress_route=EgressRoute.BY_DOMAIN,
        )

    @property
    def profiles(self) -> tuple[ProviderProfile, ...]:
        return self._profiles

    def resolve(self, url: str) -> ProviderProfile:
        hostname = urlsplit(url).hostname
        domain = (hostname or "").rstrip(".")
        if hostname is not None and any(
            domain == blocked or domain.endswith(f".{blocked}")
            for blocked in UNSUPPORTED_PROVIDER_DOMAINS
        ):
            raise RunnerFailure("provider_unsupported", status=422)
        if hostname is None:
            return self._fallback
        exact = self._by_host.get(hostname)
        if any(
            domain == root or domain.endswith(f".{root}")
            for root in _DAILYMOTION_DOMAINS
        ) and (exact is None or exact.key != ProviderKey.DAILYMOTION):
            # These aliases belong to an approved platform, but only its exact
            # declared hosts may resolve. Neither Generic nor a PeerTube host
            # entry may expand the supported Dailymotion input boundary.
            raise RunnerFailure("provider_unsupported", status=422)
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
