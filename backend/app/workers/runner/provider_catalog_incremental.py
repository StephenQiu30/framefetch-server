"""Strict profile for explicitly approved PeerTube instances."""

from __future__ import annotations

import re
from urllib.parse import SplitResult

from app.services.provider_types import (
    ProviderCapability,
    ProviderKey,
    ProviderProfileVersion,
    ProviderSupportStatus,
)
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import ProviderProfile

_PEERTUBE_VIDEO = re.compile(
    r"/(?:videos/(?:watch|embed)|w)/(?:[A-Za-z0-9_-]{22}|"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-"
    r"[0-9a-f]{12})/?",
    re.IGNORECASE,
)


def _canonical_public_url(
    url: str,
    parsed: SplitResult,
    patterns: tuple[re.Pattern[str], ...],
) -> str:
    if not any(pattern.fullmatch(parsed.path) for pattern in patterns):
        raise RunnerFailure("provider_unsupported", status=422)
    # The media identity is entirely carried by the admitted path.  Share pages
    # commonly append playlist/list/tracking state, which must not turn an
    # otherwise public single-video URL into an unsupported input.  Removing it
    # also prevents opaque query tokens from reaching the extractor.
    return parsed._replace(query="", fragment="").geturl()


def _peertube_url(url: str, parsed: SplitResult) -> str:
    return _canonical_public_url(url, parsed, (_PEERTUBE_VIDEO,))


def peertube_profile(hosts: frozenset[str]) -> ProviderProfile:
    if not hosts:
        raise ValueError("PeerTube profile requires approved instances")
    return ProviderProfile(
        key=ProviderKey.PEERTUBE,
        display_name="PeerTube",
        hosts=hosts,
        version=ProviderProfileVersion.PEERTUBE,
        capabilities=frozenset(
            {
                ProviderCapability.SINGLE_VIDEO,
                ProviderCapability.AUDIO_VIDEO_SPLIT,
            }
        ),
        support_status=ProviderSupportStatus.UNKNOWN,
        normalize_url=_peertube_url,
    )
