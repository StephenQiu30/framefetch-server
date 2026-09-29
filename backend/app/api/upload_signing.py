"""Select the browser-visible MinIO signer without changing system networking."""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import Request

from app.core.config import Settings

LOCAL_WEB_UPLOAD_HEADER = "x-framefetch-upload-client"
LOCAL_WEB_UPLOAD_VALUE = "local-web"
LOCAL_WEB_DOWNLOAD_HEADER = "x-framefetch-download-client"
LOCAL_WEB_DOWNLOAD_VALUE = "local-web"


def use_local_browser_upload_endpoint(request: Request, settings: Settings) -> bool:
    """Use loopback signing only for an explicit local Web development request."""
    if (
        settings.app_env != "development"
        or settings.minio_local_browser_endpoint is None
        or request.headers.get(LOCAL_WEB_UPLOAD_HEADER) != LOCAL_WEB_UPLOAD_VALUE
    ):
        return False
    source = request.headers.get("origin") or request.headers.get("referer")
    return _is_loopback_web_origin(source)


def use_browser_download_proxy(request: Request, settings: Settings) -> bool:
    """Use the authenticated same-origin file stream for the Web client."""
    return settings.app_env in {"development", "production"} and (
        request.headers.get(LOCAL_WEB_DOWNLOAD_HEADER) == LOCAL_WEB_DOWNLOAD_VALUE
    )


def _is_loopback_web_origin(value: str | None) -> bool:
    if value is None:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return False
    if parsed.hostname == "localhost":
        return True
    try:
        return ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False
