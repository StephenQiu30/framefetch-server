"""Inspect original metadata before yt-dlp discards entitlement fields.

Standalone: plugins also run outside the application package in a subprocess.
Absent metadata is not proof of a download grant; it retains the existing public
extraction policy. Recognized restrictions and malformed flags fail closed.
"""

from __future__ import annotations

from typing import Any, NoReturn

from yt_dlp.utils import ExtractorError  # type: ignore[import-untyped]


def reject(reason: str) -> NoReturn:
    raise ExtractorError(f"Framefetch {reason}", expected=True)


def _flag(data: dict[str, Any], *keys: str) -> bool:
    values = [data[key] for key in keys if key in data]
    if any(value not in (True, False, 0, 1, "0", "1") for value in values):
        reject("content_access_metadata_invalid")
    return any(value in (True, 1, "1") for value in values)


def _objects(data: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    result = []
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        if not isinstance(value, dict):
            reject("content_access_metadata_invalid")
        else:
            result.append(value)
    return result


def enforce_douyin_access(item: dict[str, Any]) -> None:
    charges = _objects(item, "charge_info", "chargeInfo")
    previews = _objects(item, "preview_config", "previewConfig")
    for charge in charges:
        previews.extend(_objects(charge, "preview_config", "previewConfig"))
    if any(_flag(preview, "is_preview", "isPreview") for preview in previews):
        reject("content_preview_only")
    paid = any(
        _flag(charge, "is_charge_content", "isChargeContent") for charge in charges
    )
    if paid:
        purchased = any(_flag(charge, "has_paid", "hasPaid") for charge in charges)
        reject("content_export_required" if purchased else "content_paid_only")


def enforce_bilibili_access(data: dict[str, Any]) -> None:
    if _flag(data, "is_upower_exclusive"):
        reject("content_supporter_only")


def enforce_bilibili_playinfo(data: dict[str, Any]) -> None:
    descriptions = data.get("accept_description")
    if isinstance(descriptions, list) and any(
        isinstance(value, str) and "试看" in value for value in descriptions
    ):
        reject("content_preview_only")
    if _flag(data, "is_preview"):
        reject("content_preview_only")
