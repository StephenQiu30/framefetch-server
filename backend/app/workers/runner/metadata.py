from __future__ import annotations

import base64
import math
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.services.downloads.rules.enums import DynamicRange, MediaKind, StreamKind
from app.services.downloads.rules.formats import CandidateStream
from app.workers.runner.codecs import (
    audio_codec_family,
    container_family,
    video_codec_family,
)
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.options import build_download_options
from app.workers.runner.url_policy import UrlPolicyError, validate_media_url

__all__ = [
    "MediaInspection",
    "GalleryAsset",
    "build_download_options",
    "collection_fallback_assets",
    "enrich_direct_metadata",
    "enrich_format_metadata",
    "normalize_metadata",
    "normalize_selected_format_metadata",
    "normalize_media_payload",
]

_PROVIDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}")


@dataclass(frozen=True, slots=True)
class MediaInspection:
    provider_media_id: str
    title: str
    duration_seconds: float
    extractor_key: str
    streams: tuple[CandidateStream, ...]
    media_kind: MediaKind = MediaKind.VIDEO
    asset_count: int = 0
    gallery_assets: tuple[GalleryAsset, ...] = ()
    thumbnail_urls: tuple[str, ...] = ()
    download_info: dict[str, Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    @property
    def thumbnail_url(self) -> str | None:
        return self.thumbnail_urls[0] if self.thumbnail_urls else None


@dataclass(frozen=True, slots=True)
class GalleryAsset:
    url: str
    extension: str
    width: int | None = None
    height: int | None = None


def normalize_selected_format_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Represent yt-dlp's valid top-level selected format as one candidate.

    Single-representation extractors may omit ``formats`` from
    ``--dump-single-json`` while returning a selected ``format_id`` and media
    URL at the top level. Preserve that representation for the runner's common
    bounded-probe and semantic-format pipeline.
    """
    if isinstance(payload.get("formats"), list):
        return payload
    format_id = payload.get("format_id")
    url = payload.get("url")
    if not isinstance(format_id, str) or not isinstance(url, str):
        return payload
    selected = {
        key: value
        for key, value in payload.items()
        if key
        in {
            "abr",
            "acodec",
            "dynamic_range",
            "ext",
            "filesize",
            "filesize_approx",
            "format_id",
            "fps",
            "height",
            "language",
            "tbr",
            "url",
            "vbr",
            "vcodec",
            "width",
        }
    }
    normalized = dict(payload)
    normalized["formats"] = [selected]
    return normalized


def normalize_media_payload(
    payload: dict[str, Any], *, max_assets: int
) -> dict[str, Any]:
    """Classify actual assets before attempting video-only probes.

    URL extensions describe direct representations, never arbitrary posters.
    Image-only thumbnails require explicit image metadata. Collections retain
    every member in source order; missing members and oversized lists fail closed.
    """
    if payload.get("media_kind") == MediaKind.IMAGE_GALLERY.value:
        return payload
    if _is_video_collection_payload(payload):
        entries = payload.get("entries")
        if not isinstance(entries, list) or not entries:
            raise RunnerFailure("unsupported_source")
        if len(entries) > max_assets:
            raise RunnerFailure("format_limit_exceeded", status=413)
        if any(not isinstance(entry, dict) for entry in entries):
            raise RunnerFailure("invalid_inspection_response", status=502)
        # Nested playlists need an explicit member plan, not a misleading count.
        if any(_is_video_collection_payload(entry) for entry in entries):
            raise RunnerFailure("unsupported_source")
        return payload
    asset = _image_asset(payload)
    if asset is None:
        return payload
    return {
        **payload,
        "media_kind": MediaKind.IMAGE_GALLERY.value,
        "assets": [
            {
                "url": asset.url,
                "extension": asset.extension,
                "width": asset.width,
                "height": asset.height,
            }
        ],
    }


def _image_asset(entry: dict[str, Any]) -> GalleryAsset | None:
    if _entry_declares_video(entry):
        return None
    candidates = [entry]
    formats = entry.get("formats")
    if isinstance(formats, list):
        candidates.extend(value for value in formats if isinstance(value, dict))
    images: list[dict[str, Any]] = []
    for candidate in candidates:
        url = candidate.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        extension = str(
            candidate.get("ext") or urlsplit(url).path.rsplit(".", 1)[-1]
        ).lower()
        if extension in {"jpg", "jpeg", "png", "webp"}:
            images.append({**candidate, "extension": extension})
        elif candidate is not entry or _entry_has_downloadable_format(entry):
            # A playable representation takes priority over any poster format.
            return None
    if images:
        selected = max(
            images,
            key=lambda item: (
                (_positive_int(item.get("width")) or 0)
                * (_positive_int(item.get("height")) or 0)
            ),
        )
        url = selected["url"]
        extension = selected["extension"]
    else:
        if _entry_has_downloadable_format(entry):
            return None
        url = _entry_thumbnail_url(entry)
        if url is None or not _entry_declares_image(entry, url):
            return None
        selected = entry
        extension = urlsplit(url).path.rsplit(".", 1)[-1].lower()
        if extension not in {"jpg", "jpeg", "png", "webp"}:
            extension = "jpg"
    try:
        url = validate_media_url(url).value
    except UrlPolicyError as exc:
        raise RunnerFailure("invalid_inspection_response", status=502) from exc
    return GalleryAsset(
        url=url,
        extension="jpg" if extension == "jpeg" else extension,
        width=_positive_int(selected.get("width")),
        height=_positive_int(selected.get("height")),
    )


def enrich_direct_metadata(
    payload: dict[str, Any], probe: dict[str, Any]
) -> dict[str, Any]:
    """Fill yt-dlp's sparse direct-file metadata from a proxy-bound ffprobe."""
    format_info = probe.get("format")
    probe_streams = probe.get("streams")
    raw_formats = payload.get("formats")
    if (
        not isinstance(format_info, dict)
        or not isinstance(probe_streams, list)
        or not isinstance(raw_formats, list)
    ):
        raise RunnerFailure("invalid_inspection_response", status=502)

    video = _first_probe_stream(probe_streams, "video")
    audio = _first_probe_stream(probe_streams, "audio")
    if video is None or audio is None:
        raise RunnerFailure("unsupported_source")
    duration = _positive_number(format_info.get("duration"))
    if duration is None:
        raise RunnerFailure("unsupported_source")

    enriched = dict(payload)
    enriched["duration"] = duration
    enriched_formats: list[object] = []
    for value in raw_formats:
        if not isinstance(value, dict):
            enriched_formats.append(value)
            continue
        raw = dict(value)
        raw.update(
            {
                "vcodec": video.get("codec_name"),
                "acodec": audio.get("codec_name"),
                "width": video.get("width"),
                "height": video.get("height"),
                "fps": _frame_rate(
                    video.get("avg_frame_rate") or video.get("r_frame_rate")
                ),
                "dynamic_range": _probe_dynamic_range(video),
                "language": _probe_language(audio),
                "filesize": format_info.get("size"),
                "tbr": _kilobits(format_info.get("bit_rate")),
            }
        )
        enriched_formats.append(raw)
    enriched["formats"] = enriched_formats
    return enriched


def enrich_format_metadata(
    raw: dict[str, Any],
    probe: dict[str, Any],
    *,
    prefer_nominal_fps: bool = False,
) -> dict[str, Any]:
    """Fill a single sparse yt-dlp format with bounded ffprobe metadata."""
    probe_streams = probe.get("streams")
    if not isinstance(probe_streams, list):
        return raw

    enriched = dict(raw)
    video = _first_probe_stream(probe_streams, "video")
    audio = _first_probe_stream(probe_streams, "audio")
    if video is None:
        enriched["vcodec"] = "none"
    else:
        fps = _frame_rate(video.get("avg_frame_rate")) or _frame_rate(
            video.get("r_frame_rate")
        )
        nominal = _frame_rate(video.get("r_frame_rate"))
        # Twitch clip edit lists can make the remote container average 30.016
        # or 60.017 while the actual cadence is 30/60. Keep materially different
        # averages (including variable-rate media); final-file checks stay strict.
        if (
            prefer_nominal_fps
            and fps is not None
            and nominal is not None
            and abs(fps - nominal) <= nominal * 0.001
        ):
            fps = nominal
        enriched.update(
            {
                "vcodec": video.get("codec_name") or enriched.get("vcodec"),
                "width": video.get("width") or enriched.get("width"),
                "height": video.get("height") or enriched.get("height"),
                "fps": fps or enriched.get("fps"),
                "dynamic_range": _probe_dynamic_range(video),
            }
        )
    if audio is None:
        enriched["acodec"] = "none"
    else:
        enriched.update(
            {
                "acodec": audio.get("codec_name") or enriched.get("acodec"),
                "language": _probe_language(audio) or enriched.get("language"),
            }
        )

    format_info = probe.get("format")
    if isinstance(format_info, dict):
        enriched["duration"] = _positive_number(
            format_info.get("duration")
        ) or enriched.get("duration")
        enriched["filesize"] = format_info.get("size") or enriched.get("filesize")
        enriched["tbr"] = _kilobits(format_info.get("bit_rate")) or enriched.get("tbr")
    return enriched


def normalize_metadata(
    payload: dict[str, Any],
    *,
    max_duration_seconds: float,
    max_candidate_streams: int,
    max_gallery_assets: int = 1000,
) -> MediaInspection:
    payload = normalize_media_payload(payload, max_assets=max_gallery_assets)
    if payload.get("media_kind") == MediaKind.IMAGE_GALLERY.value:
        return normalize_gallery_metadata(
            payload,
            max_assets=max_gallery_assets,
        )
    if _is_video_collection_payload(payload):
        return normalize_video_collection_metadata(
            payload,
            max_assets=max_gallery_assets,
        )
    _validate_source(payload, max_duration_seconds)
    raw_formats = payload.get("formats")
    if not isinstance(raw_formats, list):
        raise RunnerFailure("unsupported_source")

    streams: list[CandidateStream] = []
    for raw in raw_formats:
        if not isinstance(raw, dict) or raw.get("has_drm") is True:
            continue
        stream = _normalize_stream(raw, payload)
        if stream is None:
            continue
        streams.append(stream)
        if len(streams) > max_candidate_streams:
            raise RunnerFailure("format_limit_exceeded")
    if not streams:
        raise RunnerFailure("format_unavailable", status=409)

    raw_title = str(payload.get("title") or "")
    title = raw_title.strip()
    title_has_control = any(
        ord(character) < 32 or ord(character) == 127 for character in raw_title
    )
    extractor = _identity(
        payload.get("extractor_key") or payload.get("extractor"),
        max_length=128,
    )
    provider_media_id = _identity(payload.get("id"), max_length=256)
    if not title or len(title) > 4096 or title_has_control:
        raise RunnerFailure("invalid_inspection_response", status=502)
    return MediaInspection(
        provider_media_id=provider_media_id,
        title=title,
        duration_seconds=float(payload["duration"]),
        extractor_key=extractor,
        streams=tuple(streams),
        thumbnail_urls=_thumbnail_urls(payload),
        download_info=payload,
    )


def normalize_gallery_metadata(
    payload: dict[str, Any],
    *,
    max_assets: int,
) -> MediaInspection:
    raw_assets = payload.get("assets")
    if not isinstance(raw_assets, list) or not raw_assets:
        raise RunnerFailure("format_unavailable", status=409)
    if len(raw_assets) > max_assets:
        raise RunnerFailure("format_limit_exceeded", status=413)

    assets: list[GalleryAsset] = []
    for raw in raw_assets:
        if not isinstance(raw, dict) or not isinstance(raw.get("url"), str):
            raise RunnerFailure("invalid_inspection_response", status=502)
        try:
            url = validate_media_url(raw["url"]).value
        except UrlPolicyError as exc:
            raise RunnerFailure("invalid_inspection_response", status=502) from exc
        extension = str(raw.get("extension") or "jpg").casefold().lstrip(".")
        if extension not in {"jpg", "jpeg", "png", "webp"}:
            raise RunnerFailure("invalid_inspection_response", status=502)
        assets.append(
            GalleryAsset(
                url=url,
                extension="jpg" if extension == "jpeg" else extension,
                width=_positive_int(raw.get("width")),
                height=_positive_int(raw.get("height")),
            )
        )

    raw_title = str(payload.get("title") or "")
    title = raw_title.strip()
    if (
        not title
        or len(title) > 4096
        or any(ord(character) < 32 or ord(character) == 127 for character in raw_title)
    ):
        raise RunnerFailure("invalid_inspection_response", status=502)
    extractor = _identity(
        payload.get("extractor_key") or payload.get("extractor"),
        max_length=128,
    )
    provider_media_id = _identity(payload.get("id"), max_length=256)
    return MediaInspection(
        provider_media_id=provider_media_id,
        title=title,
        duration_seconds=0,
        extractor_key=extractor,
        streams=(),
        media_kind=MediaKind.IMAGE_GALLERY,
        asset_count=len(assets),
        gallery_assets=tuple(assets),
        thumbnail_urls=_thumbnail_urls(
            {"thumbnail": payload.get("thumbnail") or assets[0].url}
        ),
        download_info=payload,
    )


def normalize_video_collection_metadata(
    payload: dict[str, Any],
    *,
    max_assets: int,
) -> MediaInspection:
    """Normalize a bounded yt-dlp playlist into one ZIP-downloadable source.

    A playlist entry can be returned as metadata-only when an extractor can
    enumerate the post but cannot resolve any playable representation. Keep
    the collection as a ZIP-capable source so the download path can choose a
    provider-specific fallback (for example, an image carousel) without
    inventing a format selection.
    """
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise RunnerFailure("unsupported_source")
    if len(raw_entries) > max_assets:
        raise RunnerFailure("format_limit_exceeded", status=413)
    if any(not isinstance(entry, dict) for entry in raw_entries):
        raise RunnerFailure("invalid_inspection_response", status=502)

    raw_title = str(payload.get("title") or "")
    title = raw_title.strip()
    if (
        not title
        or len(title) > 4096
        or any(ord(character) < 32 or ord(character) == 127 for character in raw_title)
    ):
        raise RunnerFailure("invalid_inspection_response", status=502)
    extractor = _identity(
        payload.get("extractor_key") or payload.get("extractor"),
        max_length=128,
    )
    provider_media_id = _identity(payload.get("id"), max_length=256)
    fallback_assets = collection_fallback_assets(payload)
    if fallback_assets:
        return MediaInspection(
            provider_media_id=provider_media_id,
            title=title,
            duration_seconds=0,
            extractor_key=extractor,
            streams=(),
            media_kind=MediaKind.IMAGE_GALLERY,
            asset_count=len(fallback_assets),
            gallery_assets=fallback_assets,
            thumbnail_urls=_thumbnail_urls(payload),
            download_info=payload,
        )
    return MediaInspection(
        provider_media_id=provider_media_id,
        title=title,
        duration_seconds=0,
        extractor_key=extractor,
        streams=(),
        media_kind=MediaKind.VIDEO_COLLECTION,
        asset_count=len(raw_entries),
        thumbnail_urls=_thumbnail_urls(payload),
        download_info=payload,
    )


def collection_fallback_assets(
    payload: dict[str, Any],
) -> tuple[GalleryAsset, ...]:
    """Resolve every member as an image, without substituting video posters."""
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        return ()
    assets: list[GalleryAsset] = []
    for entry in entries:
        if not isinstance(entry, dict):
            return ()
        asset = _image_asset(entry)
        if asset is None:
            return ()
        assets.append(asset)
    return tuple(assets)


def _entry_has_downloadable_format(entry: dict[str, Any]) -> bool:
    """Return whether yt-dlp exposed at least one usable representation."""
    formats = entry.get("formats")
    if isinstance(formats, list):
        return any(
            isinstance(raw_format, dict)
            and isinstance(raw_format.get("format_id"), str)
            and bool(raw_format["format_id"].strip())
            and isinstance(raw_format.get("url"), str)
            and bool(raw_format["url"].strip())
            for raw_format in formats
        )
    return (
        isinstance(entry.get("format_id"), str)
        and bool(entry["format_id"].strip())
        and isinstance(entry.get("url"), str)
        and bool(entry["url"].strip())
    )


def _entry_declares_video(entry: dict[str, Any]) -> bool:
    if (
        str(entry.get("media_type") or entry.get("media_kind") or "").casefold()
        == "video"
    ):
        return True
    if _positive_number(entry.get("duration")) is not None:
        return True
    if entry.get("is_video") is True:
        return True
    if str(entry.get("__typename") or "").casefold() == "graphvideo":
        return True
    return any(
        key in entry
        for key in (
            "video_duration",
            "video_url",
            "video_versions",
            "video_dash_manifest",
        )
    )


def _entry_declares_image(entry: dict[str, Any], thumbnail: str) -> bool:
    if str(entry.get("media_type") or entry.get("media_kind") or "").casefold() in {
        "image",
        "photo",
    }:
        return True
    if entry.get("is_video") is False:
        return True
    if str(entry.get("__typename") or "").casefold() == "graphimage":
        return True
    if "image_versions2" in entry:
        return True
    return _thumbnail_is_regular_photo(thumbnail)


def _thumbnail_is_regular_photo(url: str) -> bool:
    parsed = urlsplit(url)
    if "regular_photo" in parsed.query.casefold():
        return True
    encoded = parse_qs(parsed.query).get("efg", [""])[0]
    if not encoded:
        return False
    try:
        padding = "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(f"{encoded}{padding}").decode()
    except (UnicodeDecodeError, ValueError):
        return False
    return "regular_photo" in decoded.casefold()


def _entry_thumbnail_url(entry: dict[str, Any]) -> str | None:
    direct = entry.get("thumbnail")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    thumbnails = entry.get("thumbnails")
    if not isinstance(thumbnails, list):
        return None
    candidates = [
        value
        for value in thumbnails
        if isinstance(value, dict) and isinstance(value.get("url"), str)
    ]
    if not candidates:
        return None
    selected = max(
        candidates,
        key=lambda value: (
            (_positive_int(value.get("width")) or 0)
            * (_positive_int(value.get("height")) or 0)
        ),
    )
    return str(selected["url"]).strip() or None


def _thumbnail_urls(payload: dict[str, Any]) -> tuple[str, ...]:
    candidates: list[object] = [payload.get("thumbnail")]
    thumbnails = payload.get("thumbnails")
    if isinstance(thumbnails, list):
        candidates.extend(
            value.get("url")
            for value in reversed(thumbnails)
            if isinstance(value, dict)
        )
    safe_urls: list[str] = []
    for value in candidates:
        if not isinstance(value, str):
            continue
        try:
            safe_url = validate_media_url(value).value
        except UrlPolicyError:
            continue
        if safe_url not in safe_urls:
            safe_urls.append(safe_url)
    return tuple(safe_urls)


def _is_video_collection_payload(payload: dict[str, Any]) -> bool:
    if payload.get("media_kind") == MediaKind.VIDEO_COLLECTION.value:
        return True
    media_type = str(payload.get("_type") or "").casefold()
    return media_type in {"playlist", "multi_video"} or isinstance(
        payload.get("entries"), list
    )


def _validate_source(payload: dict[str, Any], max_duration: float) -> None:
    media_type = str(payload.get("_type") or "video").casefold()
    if media_type in {"playlist", "multi_video"} or payload.get("entries") is not None:
        raise RunnerFailure("unsupported_source")
    live_status = payload.get("live_status")
    allowed_live_states = {None, "not_live", "was_live"}
    if payload.get("is_live") is True or live_status not in allowed_live_states:
        raise RunnerFailure("unsupported_source")
    if payload.get("has_drm") is True:
        raise RunnerFailure("unsupported_source")
    duration = _positive_number(payload.get("duration"))
    if duration is None:
        raise RunnerFailure("unsupported_source")
    if duration > max_duration:
        raise RunnerFailure("duration_limit_exceeded", status=422)


def _normalize_stream(
    raw: dict[str, Any],
    media: dict[str, Any],
) -> CandidateStream | None:
    raw_provider_id = str(raw.get("format_id") or "")
    if _PROVIDER_ID.fullmatch(raw_provider_id) is None or any(
        ord(character) < 32 or ord(character) == 127 for character in raw_provider_id
    ):
        raise RunnerFailure("invalid_inspection_response", status=502)
    provider_id = raw_provider_id.strip()
    video_codec = str(raw.get("vcodec") or "none")
    audio_codec = str(raw.get("acodec") or "none")
    has_video = video_codec.casefold() != "none"
    has_audio = audio_codec.casefold() != "none"
    if not provider_id or not has_video and not has_audio:
        return None
    kind = (
        StreamKind.MUXED
        if has_video and has_audio
        else StreamKind.VIDEO
        if has_video
        else StreamKind.AUDIO
    )
    height = _positive_int(raw.get("height") or media.get("height"))
    width = _positive_int(raw.get("width") or media.get("width"))
    fps = _positive_number(raw.get("fps") or media.get("fps"))
    language = raw.get("language") or media.get("language")
    bitrate = raw.get("tbr") or raw.get("vbr") or raw.get("abr")
    try:
        return CandidateStream(
            provider_id=provider_id,
            kind=kind,
            container=container_family(raw.get("ext")),
            height=height if has_video else None,
            width=width if has_video else None,
            fps=fps if has_video else None,
            dynamic_range=(
                _dynamic_range(raw.get("dynamic_range")) if has_video else None
            ),
            video_codec_family=video_codec_family(video_codec) if has_video else None,
            audio_codec_family=audio_codec_family(audio_codec) if has_audio else None,
            audio_language=language if has_audio else None,
            bitrate_kbps=_positive_int(bitrate),
            size_bytes=_positive_int(raw.get("filesize") or raw.get("filesize_approx")),
        )
    except (TypeError, ValueError):
        return None


def _positive_number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _positive_int(value: object) -> int | None:
    number = _positive_number(value)
    if number is None:
        return None
    integer = int(number)
    return integer if integer > 0 else None


def _first_probe_stream(
    streams: list[object], stream_type: str
) -> dict[str, Any] | None:
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == stream_type:
            return stream
    return None


def _frame_rate(value: object) -> float | None:
    text = str(value or "")
    numerator, separator, denominator = text.partition("/")
    if not separator:
        return _positive_number(text)
    top = _positive_number(numerator)
    bottom = _positive_number(denominator)
    return top / bottom if top is not None and bottom is not None else None


def _kilobits(value: object) -> float | None:
    bits = _positive_number(value)
    return bits / 1000 if bits is not None else None


def _probe_dynamic_range(video: dict[str, Any]) -> str:
    transfer = str(video.get("color_transfer") or "").casefold()
    return "HDR" if transfer in {"smpte2084", "arib-std-b67"} else "SDR"


def _probe_language(audio: dict[str, Any]) -> str | None:
    tags = audio.get("tags")
    language = tags.get("language") if isinstance(tags, dict) else None
    return str(language) if language else None


def _dynamic_range(value: object) -> DynamicRange:
    name = str(value or "SDR").upper()
    return DynamicRange.SDR if name in {"SDR", "SDR10"} else DynamicRange.HDR


def _identity(value: object, *, max_length: int) -> str:
    identity = str(value or "")
    has_control = any(
        ord(character) < 32 or ord(character) == 127 for character in identity
    )
    if not identity or identity != identity.strip() or len(identity) > max_length:
        raise RunnerFailure("invalid_inspection_response", status=502)
    if has_control:
        raise RunnerFailure("invalid_inspection_response", status=502)
    return identity
