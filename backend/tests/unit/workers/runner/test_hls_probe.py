from urllib.parse import urlsplit

import httpx
import pytest
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.hls_probe import read_clear_hls_prefix

URL = "https://video.twimg.com/clear/video.m3u8"
MANIFEST = (
    b'#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:3,\nfirst.m4s\n#EXT-X-ENDLIST\n'
)


async def test_clear_fmp4_probe_combines_init_and_bounded_video_prefix():
    requests = []

    def handle(request):
        requests.append(request)
        path = urlsplit(str(request.url)).path
        body = (
            MANIFEST
            if path.endswith(".m3u8")
            else b"init"
            if path.endswith("init.mp4")
            else b"x" * (512 * 1024)
        )
        return httpx.Response(200, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        data = await read_clear_hls_prefix(
            client, URL, headers={"Referer": "https://x.com/user/status/123"}
        )
    assert data == b"init" + b"x" * (256 * 1024)
    assert requests[-1].headers["Range"] == "bytes=0-262143"
    assert all("cookie" not in r.headers for r in requests)


@pytest.mark.parametrize(
    "manifest,code",
    [
        (b"not a manifest", "media_probe_failed"),
        (b"#EXTM3U\nfirst.ts\n", "media_probe_failed"),
        (
            b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\nfirst.ts\n#EXT-X-ENDLIST',
            "content_protected",
        ),
        (
            b'#EXTM3U\n#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES,URI="key"\nfirst.ts\n#EXT-X-ENDLIST',
            "content_protected",
        ),
        (
            b"#EXTM3U\n#EXT-X-BYTERANGE:100@10\nfirst.ts\n#EXT-X-ENDLIST",
            "media_probe_failed",
        ),
        (b"#EXTM3U\nhttp://127.0.0.1/first.ts\n#EXT-X-ENDLIST", "invalid_url"),
        (
            b"#EXTM3U\nhttps://other.example.com/first.ts\n#EXT-X-ENDLIST",
            "media_probe_failed",
        ),
        (
            b"#EXTM3U\nfirst.ts\nhttps://other.example.com/last.ts\n#EXT-X-ENDLIST",
            "media_probe_failed",
        ),
        (
            b'#EXTM3U\n#EXT-X-MAP:URI="init.mp4",BYTERANGE="100@10"\nfirst.ts\n#EXT-X-ENDLIST',
            "media_probe_failed",
        ),
        (
            b'#EXTM3U\n#EXT-X-MAP:URI="a.mp4"\nfirst.m4s\n#EXT-X-MAP:URI="b.mp4"\nsecond.m4s\n#EXT-X-ENDLIST',
            "media_probe_failed",
        ),
        (b"x" * 2_000_001, "media_probe_failed"),
    ],
)
async def test_probe_rejects_unsafe_or_unsupported_manifest_before_media_io(
    manifest, code
):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=manifest)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(RunnerFailure) as error:
            await read_clear_hls_prefix(client, URL, headers={})
    assert error.value.code == code
    assert len(requests) == 1


async def test_oversized_init_is_rejected_before_fragment_io():
    paths = []

    def handle(request):
        paths.append(request.url.path)
        return httpx.Response(
            200, content=MANIFEST if len(paths) == 1 else b"x" * (256 * 1024 + 1)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(RunnerFailure) as error:
            await read_clear_hls_prefix(client, URL, headers={})
    assert error.value.code == "media_probe_failed"
    assert len(paths) == 2
