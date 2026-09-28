"""Fail-closed content entitlement checks before provider media access."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.provider_types import ProviderAccessMode, ProviderKey
from app.workers.runner.errors import RunnerFailure

_ALLOWED_YOUTUBE_AVAILABILITY = {"public", "unlisted"}
_RESTRICTED_AVAILABILITY = {
    "private": "content_private",
    "premium_only": "content_not_entitled",
    "subscriber_only": "content_not_entitled",
    "vip_only": "content_not_entitled",
    "paid": "content_not_entitled",
    "purchase_required": "content_not_entitled",
    "preview": "content_not_entitled",
    "needs_auth": "credential_required",
}
_ACCOUNT_ENTITLEMENT_AVAILABILITY = {
    "premium_only",
    "subscriber_only",
    "vip_only",
    "paid",
}
_ACCOUNT_ENTITLEMENT_FLAGS = (
    "is_premium",
    "is_member_only",
)


def enforce_media_rights(
    payload: Mapping[str, Any],
    *,
    provider_key: str,
    access_mode: ProviderAccessMode,
) -> None:
    if _has_drm(payload):
        raise RunnerFailure("drm_protected", status=422)
    personal = (
        provider_key in {ProviderKey.YOUKU, ProviderKey.QQVIDEO}
        and access_mode is ProviderAccessMode.OPERATOR_MANAGED
    )
    availability = payload.get("availability")
    if isinstance(availability, str):
        normalized = availability.casefold()
        if personal and normalized in _ACCOUNT_ENTITLEMENT_AVAILABILITY:
            raise RunnerFailure("credential_entitlement_drift", status=422)
        restricted = _RESTRICTED_AVAILABILITY.get(normalized)
        if restricted is not None and not (
            personal
            and normalized in {"premium_only", "subscriber_only", "vip_only", "paid"}
        ):
            raise RunnerFailure(restricted, status=403)
        if (
            provider_key == ProviderKey.YOUTUBE
            and normalized not in _ALLOWED_YOUTUBE_AVAILABILITY
        ):
            raise RunnerFailure("content_entitlement_unknown", status=422)
    if payload.get("is_private") is True:
        raise RunnerFailure("content_private", status=403)
    if personal and any(
        payload.get(field) is True for field in _ACCOUNT_ENTITLEMENT_FLAGS
    ):
        raise RunnerFailure("credential_entitlement_drift", status=422)
    restricted_flags: tuple[str, ...] = ("is_preview", "requires_purchase")
    if not personal:
        restricted_flags += ("is_premium", "is_member_only")
    if any(payload.get(field) is True for field in restricted_flags):
        raise RunnerFailure("content_not_entitled", status=403)
    if (personal or provider_key == ProviderKey.QQVIDEO) and payload.get(
        "_framefetch_full_stream"
    ) is not True:
        raise RunnerFailure("content_access_metadata_invalid", status=422)
    entries = payload.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, Mapping):
                enforce_media_rights(
                    entry, provider_key=provider_key, access_mode=access_mode
                )
    if access_mode is not ProviderAccessMode.OPERATOR_MANAGED:
        return
    if provider_key == ProviderKey.YOUTUBE and not isinstance(availability, str):
        raise RunnerFailure("content_entitlement_unknown", status=422)


def _has_drm(payload: Mapping[str, Any]) -> bool:
    if payload.get("has_drm") is True:
        return True
    formats = payload.get("formats")
    if not isinstance(formats, list) or not formats:
        return False
    playable = [item for item in formats if isinstance(item, dict)]
    return bool(playable) and all(item.get("has_drm") is True for item in playable)
