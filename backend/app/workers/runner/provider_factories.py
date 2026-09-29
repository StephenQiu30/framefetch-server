"""Reusable factories for common provider policy families."""

from __future__ import annotations

from app.services.provider_types import (
    ProviderAccessMode,
    ProviderCapability,
    ProviderProfileVersion,
    ProviderSupportStatus,
)
from app.workers.runner.provider_registry import (
    ProviderProfile,
    RuntimeCommandArgs,
    UrlNormalizer,
    default_runtime_command_args,
    identity_url,
)

CHROME_IMPERSONATION: tuple[str, ...] = (
    "--impersonate",
    "Chrome-136:Macos-15",
)
ANDROID_IMPERSONATION: tuple[str, ...] = (
    "--impersonate",
    "Chrome-131:Android-14",
)
STANDARD_CAPABILITIES = frozenset(
    {
        ProviderCapability.SINGLE_VIDEO,
        ProviderCapability.AUDIO_VIDEO_SPLIT,
    }
)
CHALLENGED_CAPABILITIES = frozenset(
    {
        ProviderCapability.SINGLE_VIDEO,
        ProviderCapability.SHORT_VIDEO,
        ProviderCapability.AUDIO_VIDEO_SPLIT,
    }
)


def standard_provider(
    key: str,
    display_name: str,
    hosts: tuple[str, ...],
    *,
    version: str = ProviderProfileVersion.DEFAULT,
    normalize_url: UrlNormalizer = identity_url,
    capabilities: frozenset[ProviderCapability] = STANDARD_CAPABILITIES,
    status: ProviderSupportStatus = ProviderSupportStatus.UNKNOWN,
    host_suffixes: frozenset[str] = frozenset(),
    operator_cookie_domains: frozenset[str] = frozenset(),
    anonymous_access: bool = True,
    command_args: tuple[str, ...] = (),
    runtime_command_args: RuntimeCommandArgs = default_runtime_command_args,
    client_profile_id: str = "yt-dlp-default",
    canary_suite: str = "anonymous-metadata-range",
    inspection_attempts: int = 2,
    inspection_retry_delay: float = 1,
    probe_authenticated_media: bool = False,
    probe_media_duration: bool = False,
) -> ProviderProfile:
    access_modes: tuple[ProviderAccessMode, ...] = (
        (ProviderAccessMode.ANONYMOUS,) if anonymous_access else ()
    )
    if operator_cookie_domains:
        access_modes += (ProviderAccessMode.OPERATOR_MANAGED,)
    if not access_modes:
        raise ValueError("provider must allow at least one access mode")
    return ProviderProfile(
        key=key,
        display_name=display_name,
        hosts=frozenset(hosts),
        host_suffixes=host_suffixes,
        version=version,
        capabilities=capabilities,
        support_status=status,
        access_modes=access_modes,
        cookie_domain_allowlist=operator_cookie_domains,
        client_profile_id=client_profile_id,
        credential_concurrency=1 if operator_cookie_domains else 0,
        canary_suite=canary_suite,
        command_args=command_args,
        runtime_command_args=runtime_command_args,
        inspection_attempts=inspection_attempts,
        inspection_retry_delay=inspection_retry_delay,
        probe_authenticated_media=probe_authenticated_media,
        probe_media_duration=probe_media_duration,
        normalize_url=normalize_url,
    )


def challenged_provider(
    key: str,
    display_name: str,
    hosts: tuple[str, ...],
    *,
    version: str = ProviderProfileVersion.DEFAULT,
    normalize_url: UrlNormalizer = identity_url,
    status: ProviderSupportStatus = ProviderSupportStatus.UNKNOWN,
    operator_cookie_domains: frozenset[str] = frozenset(),
    anonymous_access: bool = True,
    command_args: tuple[str, ...] = CHROME_IMPERSONATION,
    client_profile_id: str = "chrome-136-macos-15",
    runtime_command_args: RuntimeCommandArgs = default_runtime_command_args,
    canary_suite: str = "anonymous-metadata-range",
    probe_authenticated_media: bool = False,
    probe_media_duration: bool = False,
) -> ProviderProfile:
    return standard_provider(
        key,
        display_name,
        hosts,
        version=version,
        normalize_url=normalize_url,
        capabilities=CHALLENGED_CAPABILITIES,
        status=status,
        operator_cookie_domains=operator_cookie_domains,
        anonymous_access=anonymous_access,
        command_args=command_args,
        runtime_command_args=runtime_command_args,
        client_profile_id=client_profile_id,
        canary_suite=canary_suite,
        inspection_attempts=8,
        inspection_retry_delay=0.5,
        probe_authenticated_media=probe_authenticated_media,
        probe_media_duration=probe_media_duration,
    )
