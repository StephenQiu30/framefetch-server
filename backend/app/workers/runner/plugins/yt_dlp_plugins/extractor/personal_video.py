"""Personal clear-stream adapters; credentials remain inside the yt-dlp process.

Uses the pinned upstream extractors. A login is not evidence of completeness:
Youku segment coverage and Tencent page/API durations must independently agree.
Unknown responses fail closed and require a parser update, not a startup repair.
"""

from __future__ import annotations

import json
import math
from typing import Any
from urllib.parse import urljoin

from yt_dlp.extractor.tencent import VQQVideoIE  # type: ignore[import-untyped]
from yt_dlp.extractor.youku import YoukuIE  # type: ignore[import-untyped]

from ._content_access import reject


def positive_duration(value: Any) -> float:
    try:
        number = float(value) if not isinstance(value, bool) else 0
    except (TypeError, ValueError, OverflowError):
        number = 0
    if not math.isfinite(number) or number <= 0:
        reject("content_access_metadata_invalid")
    return number


def same_duration(actual: Any, expected: float) -> None:
    if abs(positive_duration(actual) - expected) > max(3, expected * 0.02):
        reject("content_preview_only")


def full_youku_streams(data: dict[str, Any]) -> list[dict[str, Any]]:
    video = data.get("video")
    if not isinstance(video, dict):
        reject("content_access_metadata_invalid")
    duration = positive_duration(video.get("seconds"))
    streams = data.get("stream")
    if not isinstance(streams, list) or not streams:
        reject("content_access_metadata_invalid")
    complete = []
    for stream in streams:
        if not isinstance(stream, dict):
            reject("content_access_metadata_invalid")
        if stream.get("channel_type") == "tail":
            continue
        segments = stream.get("segs")
        if not isinstance(segments, list) or not segments:
            reject("content_access_metadata_invalid")
        if any(not isinstance(seg, dict) for seg in segments):
            reject("content_access_metadata_invalid")
        # you-get also identifies missing cdn_url as a preview restriction.
        if any(
            not isinstance(seg.get("cdn_url"), str) or not seg["cdn_url"]
            for seg in segments
        ):
            continue
        # The original video duration is retained for post-download ffprobe;
        # never substitute the shorter preview's duration.
        milliseconds = stream.get("milliseconds_video")
        if milliseconds is not None:
            if abs(positive_duration(milliseconds) / 1000 - duration) > max(
                3, duration * 0.02
            ):
                continue
        complete.append(stream)
    if not complete:
        reject("content_preview_only")
    return complete


class _YoukuPersonalIE(YoukuIE, plugin_name="personal_video"):  # type: ignore[misc, call-arg]
    def _download_json(
        self, url_or_request: Any, video_id: str, *args: Any, **kwargs: Any
    ) -> Any:
        if url_or_request == "https://ups.youku.com/ups/get.json":
            cna = self._get_cookies("https://ups.youku.com/").get("cna")
            if cna is not None and cna.value:
                kwargs["query"] = {**(kwargs.get("query") or {}), "utid": cna.value}
        result = super()._download_json(url_or_request, video_id, *args, **kwargs)
        if url_or_request == "https://ups.youku.com/ups/get.json":
            if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
                reject("content_access_metadata_invalid")
            data = result["data"]
            if not data.get("error"):
                data["stream"] = full_youku_streams(data)
        return result

    def _real_extract(self, url: str) -> Any:
        result = super()._real_extract(url)
        duration = positive_duration(result.get("duration"))
        clear_formats = []
        saw_drm = False
        for original in result["formats"]:
            # Upstream Youku emits a URL without parsing the manifest. Parse it
            # here so yt-dlp can identify DRM before exposing a selectable format.
            formats = self._extract_m3u8_formats(
                original["url"], result["id"], "mp4", m3u8_id=original["format_id"]
            )
            for item in formats:
                if item.get("has_drm"):
                    saw_drm = True
                    continue
                clear_formats.append({**original, **item})
        if not clear_formats:
            reject("drm_protected" if saw_drm else "content_access_metadata_invalid")
        result["formats"] = clear_formats
        result["duration"] = duration
        result["_framefetch_full_stream"] = True
        return result


class _VQQPersonalIE(VQQVideoIE, plugin_name="personal_video"):  # type: ignore[misc, call-arg]
    _full_duration: float | None = None
    _saw_drm = False
    _source_url = "https://v.qq.com/"
    _inline_manifest: str | None = None

    def _media_headers(self) -> dict[str, str]:
        return {"Referer": self._source_url, "Origin": "https://v.qq.com"}

    def _real_extract(self, url: str) -> Any:
        self._source_url = url
        self._full_duration = None
        self._saw_drm = False
        result = super()._real_extract(url)
        if not result.get("formats"):
            reject(
                "drm_protected" if self._saw_drm else "content_access_metadata_invalid"
            )
        result["duration"] = positive_duration(self._full_duration)
        result["_framefetch_full_stream"] = True
        result["http_headers"] = self._media_headers()
        return result

    def _get_webpage_metadata(self, webpage: str, video_id: str) -> Any:
        startup = self._search_json(
            r"window\.__STARTUP_CONFIG__\s*=", webpage, "startup config", video_id
        )
        config = startup.get("vinfoConfig") if isinstance(startup, dict) else None
        if not isinstance(config, dict):
            reject("content_access_metadata_invalid")
        host = config.get("vinfoProxyDomain")
        if host not in {"vd6.l.qq.com", "vd.l.qq.com"}:
            reject("content_access_metadata_invalid")
        keys = ("playerVersion", "adVersion", "vinfoProtoVer", "adProtoVer")
        if any(not isinstance(config.get(key), str) or not config[key] for key in keys):
            reject("content_access_metadata_invalid")
        matched = self._match_valid_url(self._source_url)
        cid = matched.group("series_id") or ""
        params = {key: config[key] for key in keys}
        params["href"] = self._source_url
        cookie = "; ".join(
            f"{name}={item.value}"
            for name, item in self._get_cookies("https://v.qq.com/").items()
        )
        response = self._download_json(
            f"https://{host}/vinfo_proxy",
            video_id,
            "Downloading video metadata",
            data=json.dumps(
                {
                    "cid": cid,
                    "vid": video_id,
                    "vqqcookie": cookie,
                    "playParams": {},
                    "vinfoParams": params,
                }
            ).encode(),
            headers={
                "Content-Type": "text/plain",
                "Origin": "https://v.qq.com",
                "Referer": self._source_url,
            },
        )
        if not isinstance(response, dict) or response.get("ret") != 0:
            reject("content_access_metadata_invalid")
        data = response.get("data")
        if not isinstance(data, dict):
            reject("content_access_metadata_invalid")
        video, play = data.get("videoInfo"), data.get("playInfo")
        if (
            not isinstance(video, dict)
            or video.get("vid") != video_id
            or not isinstance(play, dict)
            or play.get("vid") != video_id
            or (cid and play.get("cid") != cid)
        ):
            reject("content_access_metadata_invalid")
        self._full_duration = positive_duration(video.get("duration"))
        # proxyhttp.vinfo may be an encrypted envelope (enc=1). It is not a
        # manifest or evidence of media DRM; leave it untouched. The pinned
        # playback extractor obtains formats separately and checks their DRM.
        return {"global": {"videoInfo": video, "coverInfo": data.get("coverInfo", {})}}

    def _download_webpage(
        self, url_or_request: Any, video_id: str, *args: Any, **kwargs: Any
    ) -> Any:
        if url_or_request == self._API_URL:
            cookies = self._get_cookies("https://v.qq.com/")
            mapping = {
                "vuserid": "v_vuserid",
                "vusession": "v_vusession",
                "main_login": "v_main_login",
                "openid": "v_t_openid",
                "appid": "v_t_appid",
                "access_token": "v_t_access_token",
            }
            token = {
                key: cookies[name].value
                for key, name in mapping.items()
                if name in cookies
            }
            if not token.get("vuserid") or not token.get("vusession"):
                reject("credential_required")
            # Exact Tencent API only; never copy the account token to CDN requests
            # or include it in argv, metadata, application logs or stored plans.
            query = dict(kwargs.get("query") or {})
            query["logintoken"] = json.dumps(token, separators=(",", ":"))
            kwargs["query"] = query
        return super()._download_webpage(url_or_request, video_id, *args, **kwargs)

    def _extract_m3u8_formats_and_subtitles(
        self, m3u8_url: str, video_id: str, ext: str = "mp4", **kwargs: Any
    ) -> Any:
        kwargs["headers"] = {**(kwargs.get("headers") or {}), **self._media_headers()}
        if self._inline_manifest is not None:
            formats, subtitles = self._parse_m3u8_formats_and_subtitles(
                self._inline_manifest, m3u8_url, ext=ext, video_id=video_id, **kwargs
            )
            segments = [
                line.strip()
                for line in self._inline_manifest.splitlines()
                if line.strip() and not line.startswith("#")
            ]
            for item in formats:
                item["hls_media_playlist_data"] = self._inline_manifest
                item["http_headers"] = self._media_headers()
                # A clear TS segment supplies codecs without fetching the slow
                # CDN playlist again. Keep the full source duration separately.
                if segments and not any(
                    tag in self._inline_manifest
                    for tag in ("#EXT-X-KEY", "#EXT-X-MAP", "#EXT-X-BYTERANGE")
                ):
                    item["_framefetch_probe_url"] = urljoin(m3u8_url, segments[0])
        else:
            formats, subtitles = super()._extract_m3u8_formats_and_subtitles(
                m3u8_url, video_id, ext, **kwargs
            )
        # Tencent's upstream common_info overwrites has_drm with the API flag.
        # Remove manifest-detected DRM first, so a clear API flag cannot erase it.
        self._saw_drm = self._saw_drm or any(item.get("has_drm") for item in formats)
        return [item for item in formats if not item.get("has_drm")], subtitles

    def _extract_video_formats_and_subtitles(
        self, api_response: Any, video_id: str
    ) -> Any:
        if not isinstance(api_response, dict):
            reject("content_access_metadata_invalid")
        vl = api_response.get("vl")
        if not isinstance(vl, dict):
            reject("content_access_metadata_invalid")
        videos = vl.get("vi")
        if (
            not isinstance(videos, list)
            or len(videos) != 1
            or not isinstance(videos[0], dict)
        ):
            reject("content_access_metadata_invalid")
        video = videos[0]
        if video.get("vid") != video_id:
            reject("content_access_metadata_invalid")
        same_duration(video.get("td"), positive_duration(self._full_duration))
        preview = api_response.get("preview")
        if preview is not None and preview not in (0, "0"):
            same_duration(preview, positive_duration(self._full_duration))
        urls = video.get("ul")
        if not isinstance(urls, dict):
            reject("content_access_metadata_invalid")
        mirrors = urls.get("ui")
        if not isinstance(mirrors, list) or not mirrors:
            reject("content_access_metadata_invalid")
        self._inline_manifest = None
        manifest = urls.get("m3u8")
        if manifest is not None:
            if (
                not isinstance(manifest, str)
                or not manifest.startswith("#EXTM3U")
                or "#EXT-X-ENDLIST" not in manifest
                or "#EXT-X-TARGETDURATION" not in manifest
                or len(manifest) > 2_000_000
            ):
                reject("content_access_metadata_invalid")
            duration = sum(
                positive_duration(line.partition(":")[2].partition(",")[0])
                for line in manifest.splitlines()
                if line.startswith("#EXTINF:")
            )
            same_duration(duration, positive_duration(self._full_duration))
            self._inline_manifest = manifest
        # Each ui entry is another CDN for the same rendition. Probe one usable
        # mirror per quality instead of downloading every equivalent manifest.
        for mirror in mirrors[:4]:
            candidate = {
                **api_response,
                "vl": {**vl, "vi": [{**video, "ul": {**urls, "ui": [mirror]}}]},
            }
            formats, subtitles = super()._extract_video_formats_and_subtitles(
                candidate, video_id
            )
            self._saw_drm = self._saw_drm or any(
                item.get("has_drm") for item in formats
            )
            clear = [item for item in formats if not item.get("has_drm")]
            if clear:
                return clear, subtitles
        return [], {}
