"""Reusable factories for common provider policy families."""

from __future__ import annotations

from typing import Literal

from app.services.provider_types import (
    ProviderCapability,
    ProviderIdentity,
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
    identity: ProviderIdentity = ProviderIdentity.NONE,
    content_scope: Literal["public", "personal_full"] = "public",
    cookie_domain_allowlist: frozenset[str] = frozenset(),
    command_args: tuple[str, ...] = (),
    runtime_command_args: RuntimeCommandArgs = default_runtime_command_args,
    client_profile: str = "yt-dlp-default",
    probe_authenticated_media: bool = False,
    probe_media_duration: bool = False,
) -> ProviderProfile:
    return ProviderProfile(
        key=key,
        display_name=display_name,
        hosts=frozenset(hosts),
        host_suffixes=host_suffixes,
        version=version,
        capabilities=capabilities,
        support_status=status,
        identity=identity,
        content_scope=content_scope,
        cookie_domain_allowlist=cookie_domain_allowlist,
        client_profile=client_profile,
        command_args=command_args,
        runtime_command_args=runtime_command_args,
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
    identity: ProviderIdentity = ProviderIdentity.NONE,
    content_scope: Literal["public", "personal_full"] = "public",
    cookie_domain_allowlist: frozenset[str] = frozenset(),
    command_args: tuple[str, ...] = CHROME_IMPERSONATION,
    client_profile: str = "chrome-136-macos-15",
    runtime_command_args: RuntimeCommandArgs = default_runtime_command_args,
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
        identity=identity,
        content_scope=content_scope,
        cookie_domain_allowlist=cookie_domain_allowlist,
        command_args=command_args,
        runtime_command_args=runtime_command_args,
        client_profile=client_profile,
        probe_authenticated_media=probe_authenticated_media,
        probe_media_duration=probe_media_duration,
    )
