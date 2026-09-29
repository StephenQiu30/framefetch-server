from __future__ import annotations

from typing import Any, cast
from urllib.parse import urlsplit

from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_normalizers import tiktok_url
from yt_dlp.extractor.tiktok import (  # type: ignore[import-untyped]
    TikTokIE,
    TikTokVMIE,
)
from yt_dlp.networking import HEADRequest  # type: ignore[import-untyped]
from yt_dlp.networking.exceptions import (  # type: ignore[import-untyped]
    RequestError,
)
from yt_dlp.utils import ExtractorError  # type: ignore[import-untyped]

PLAYER_UNAVAILABLE = "TikTok video not available from the official player"
PLAYER_TEMPORARY = "TikTok official player API temporarily unavailable"
PLAYER_SCHEMA_CHANGED = "TikTok official player response structure changed"
_UNAVAILABLE_MARKERS = ("video not available", "log into an account", "requiring login")
_REGRESSION_MARKERS = (
    "unexpected response from webpage request",
    "unable to extract challenge data",
    "unable to solve js challenge",
    "unable to extract universal data",
    "unable to extract webpage",
)


class _TikTokPublicPlayerIE(TikTokIE, plugin_name="public_player"):  # type: ignore[misc, call-arg]
    """Public TikTok videos through upstream yt-dlp's maintained web extractor.

    TikTok's first-party player API now requires per-request signatures
    (msToken/X-Bogus/X-Gnarly) and answers 403 without them, so it is no longer
    a usable public source. Upstream yt-dlp tracks the public watch page
    (browser-impersonated request plus its own challenge handling) and ships
    fixes within days, so this class only maps its failures onto the stable
    Runner error vocabulary and never adds credentials or private-content paths.
    """

    def _real_extract(self, url: str) -> dict[str, Any]:
        video_id = self._match_valid_url(url).group("id")
        try:
            return cast(dict[str, Any], super()._real_extract(url))
        except ExtractorError as exc:
            raise _mapped_failure(exc, video_id) from exc


def _player_failure(message: str, video_id: str) -> ExtractorError:
    return ExtractorError(message, video_id=video_id, expected=True)


def _mapped_failure(exc: ExtractorError, video_id: str) -> ExtractorError:
    message = (exc.orig_msg or str(exc)).casefold()
    if "your ip address is blocked" in message:
        return _player_failure(str(exc.orig_msg or exc), video_id)
    if isinstance(exc.cause, RequestError):
        return _player_failure(PLAYER_TEMPORARY, video_id)
    if any(marker in message for marker in _UNAVAILABLE_MARKERS):
        return _player_failure(PLAYER_UNAVAILABLE, video_id)
    if any(marker in message for marker in _REGRESSION_MARKERS):
        return _player_failure(PLAYER_SCHEMA_CHANGED, video_id)
    return _player_failure(PLAYER_TEMPORARY, video_id)


class _TikTokPublicShortIE(TikTokVMIE, plugin_name="public_short"):  # type: ignore[misc, call-arg]
    """Resolve official short links only when they target a public video."""

    def _real_extract(self, url: str) -> dict[str, Any]:
        video_id = self._match_id(url)
        try:
            response = self._request_webpage(
                HEADRequest(url),
                video_id,
                note="Resolving TikTok public video link",
            )
        except ExtractorError as exc:
            message = (
                PLAYER_TEMPORARY
                if isinstance(exc.cause, RequestError)
                else PLAYER_SCHEMA_CHANGED
            )
            raise _player_failure(message, video_id) from exc
        redirected = getattr(response, "url", None)
        if not isinstance(redirected, str):
            raise _player_failure(PLAYER_SCHEMA_CHANGED, video_id)
        try:
            normalized = tiktok_url(redirected, urlsplit(redirected))
        except RunnerFailure as exc:
            raise _player_failure(PLAYER_UNAVAILABLE, video_id) from exc
        if not _TikTokPublicPlayerIE.suitable(normalized):
            raise _player_failure(PLAYER_UNAVAILABLE, video_id)
        return cast(
            dict[str, Any],
            self.url_result(normalized, ie=_TikTokPublicPlayerIE.ie_key()),
        )
