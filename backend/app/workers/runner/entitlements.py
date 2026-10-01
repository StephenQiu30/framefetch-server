"""Fail-closed content entitlement checks before provider media access."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.provider_types import ProviderKey
from app.workers.runner.errors import RunnerFailure

_ALLOWED_YOUTUBE_AVAILABILITY = {"public", "unlisted"}
_RESTRICTED_AVAILABILITY = {
    "private": "content_unavailable",
    "premium_only": "content_unavailable",
    "subscriber_only": "content_unavailable",
    "vip_only": "content_unavailable",
    "paid": "content_unavailable",
    "purchase_required": "content_unavailable",
    "preview": "content_unavailable",
    "needs_auth": "login_required",
}


def enforce_media_rights(
    payload: Mapping[str, Any],
    *,
    provider_key: str,
) -> None:
    if _has_drm(payload):
        raise RunnerFailure("content_protected", status=422)
    availability = payload.get("availability")
    if isinstance(availability, str):
        normalized = availability.casefold()
        restricted = _RESTRICTED_AVAILABILITY.get(normalized)
        if restricted is not None:
            raise RunnerFailure(restricted, status=403)
        if (
            provider_key == ProviderKey.YOUTUBE
            and normalized not in _ALLOWED_YOUTUBE_AVAILABILITY
        ):
            raise RunnerFailure("content_unavailable", status=422)
    if payload.get("is_private") is True:
        raise RunnerFailure("content_unavailable", status=403)
    restricted_flags = (
        "is_preview",
        "requires_purchase",
        "is_premium",
        "is_member_only",
    )
    if any(payload.get(field) is True for field in restricted_flags):
        raise RunnerFailure("content_unavailable", status=403)
    if (
        provider_key == ProviderKey.QQVIDEO
        and payload.get("_framefetch_full_stream") is not True
    ):
        raise RunnerFailure("content_unavailable", status=422)
    entries = payload.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, Mapping):
                enforce_media_rights(entry, provider_key=provider_key)


def _has_drm(payload: Mapping[str, Any]) -> bool:
    if payload.get("has_drm") is True:
        return True
    formats = payload.get("formats")
    if not isinstance(formats, list) or not formats:
        return False
    playable = [item for item in formats if isinstance(item, dict)]
    return bool(playable) and all(item.get("has_drm") is True for item in playable)
