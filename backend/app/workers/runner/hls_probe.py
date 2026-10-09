"""Read a bounded, clear VOD codec sample without downloading the whole HLS."""

from collections.abc import Mapping
from urllib.parse import urljoin, urlsplit

import httpx
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.utilities import safe_media_url
from yt_dlp.utils import parse_m3u8_attributes  # type: ignore[import-untyped]

_MANIFEST_LIMIT = 2_000_000
_PREFIX_LIMIT = 256 * 1024


async def read_clear_hls_prefix(
    client: httpx.AsyncClient, url: str, *, headers: Mapping[str, str]
) -> bytes:
    url = safe_media_url(url)
    document = await _read(client, url, headers, _MANIFEST_LIMIT, complete=True)
    try:
        lines = [
            line.strip() for line in document.decode().splitlines() if line.strip()
        ]
    except UnicodeError as exc:
        raise RunnerFailure("media_probe_failed", status=502) from exc
    if not lines or lines[0] != "#EXTM3U":
        raise RunnerFailure("media_probe_failed", status=502)
    if any(
        line.upper().startswith(("#EXT-X-KEY", "#EXT-X-SESSION-KEY")) for line in lines
    ):
        raise RunnerFailure("content_protected", status=422)
    if "#EXT-X-ENDLIST" not in lines or any(
        line.startswith(
            (
                "#EXT-X-STREAM-INF",
                "#EXT-X-BYTERANGE",
                "#EXT-X-GAP",
                "#EXT-X-PART",
                "#EXT-X-I-FRAME",
                "#EXT-X-SKIP",
                "#EXT-X-PRELOAD-HINT",
            )
        )
        for line in lines
    ):
        raise RunnerFailure("media_probe_failed", status=502)
    segments = [line for line in lines if not line.startswith("#")]
    maps = [line[11:] for line in lines if line.startswith("#EXT-X-MAP:")]
    if not segments or len(maps) > 1:
        raise RunnerFailure("media_probe_failed", status=502)

    def media_url(uri: str) -> str:
        candidate = safe_media_url(urljoin(url, uri))
        if urlsplit(candidate).netloc != urlsplit(url).netloc:
            raise RunnerFailure("media_probe_failed", status=502)
        return candidate

    segment_urls = [media_url(uri) for uri in segments]
    init = b""
    if maps:
        attributes = parse_m3u8_attributes(maps[0])
        uri = attributes.get("URI")
        if not isinstance(uri, str) or not uri or "BYTERANGE" in attributes:
            raise RunnerFailure("media_probe_failed", status=502)
        init = await _read(
            client, media_url(uri), headers, _PREFIX_LIMIT, complete=True
        )
    prefix = await _read(
        client, segment_urls[0], headers, _PREFIX_LIMIT, complete=False
    )
    return init + prefix


async def _read(
    client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    limit: int,
    *,
    complete: bool,
) -> bytes:
    request_headers = {**headers, "Accept-Encoding": "identity"}
    if not complete:
        request_headers["Range"] = f"bytes=0-{limit - 1}"
    async with client.stream("GET", url, headers=request_headers) as response:
        response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=65536):
            if complete and len(data) + len(chunk) > limit:
                raise RunnerFailure("media_probe_failed", status=502)
            data.extend(chunk[: limit - len(data)])
            if not complete and len(data) == limit:
                break
    if not data:
        raise RunnerFailure("media_probe_failed", status=502)
    return bytes(data)
