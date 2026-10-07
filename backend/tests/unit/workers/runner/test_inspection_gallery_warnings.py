from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from app.services.downloads.rules.content_restrictions import ContentRestriction
from app.services.downloads.rules.enums import MediaKind
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.plugins.yt_dlp_plugins.extractor.douyin_note import DouyinNoteIE
from app.workers.runner.process import ProcessResult
from app.workers.runner.utilities import normalize_for_settings
from helpers import bound_commands as MediaCommands
from helpers import settings
from yt_dlp import YoutubeDL

URL = "https://www.douyin.com/note/123"
WARNING = b"[DouyinNote] unable to extract Douyin router data"


def gallery() -> dict[str, object]:
    return {
        "id": "123",
        "extractor_key": "DouyinNote",
        "title": "Public image fixture",
        "media_kind": "image_gallery",
        "assets": [{"url": "https://cdn.example/image.webp", "extension": "webp"}],
    }


def commands(tmp_path: Path, payload: dict, warning: bytes = WARNING) -> MediaCommands:
    supervisor = AsyncMock()
    supervisor.run.return_value = ProcessResult(
        0, json.dumps(payload).encode(), warning, False, False
    )
    return MediaCommands(settings(tmp_path), supervisor)


async def test_real_flight_fallback_warning_keeps_successful_gallery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = Mock()
    extractor = DouyinNoteIE(YoutubeDL({"logger": logger, "quiet": True}))
    detail = {
        "awemeId": "123",
        "desc": "Public image fixture",
        "images": [{"urlList": ["https://cdn.example/image.webp"]}],
    }
    flight = "7:" + json.dumps(["$", "$L9", None, {"aweme": {"detail": detail}}])
    webpage = f"self.__pace_f.push([1,{json.dumps(flight)}])"
    monkeypatch.setattr(extractor, "_download_json", lambda *a, **k: {})
    monkeypatch.setattr(
        extractor,
        "_download_webpage",
        lambda url, *a, **k: webpage if "www.douyin.com/note/123/" in url else "",
    )
    # Keep the real JSON parser: its non-fatal warning is the regression trigger.
    info = extractor._real_extract(URL)
    info["extractor_key"] = "DouyinNote"  # Added by yt-dlp around _real_extract.
    warning = "\n".join(call.args[0] for call in logger.warning.call_args_list).encode()
    assert WARNING in warning
    assert info["media_kind"] == "image_gallery"

    payload = await commands(tmp_path, info, warning).inspect(URL, tmp_path)
    inspection = normalize_for_settings(payload, settings(tmp_path))

    assert inspection.media_kind is MediaKind.IMAGE_GALLERY
    assert inspection.asset_count == 1
    assert inspection.gallery_assets[0].url == "https://cdn.example/image.webp"


@pytest.mark.parametrize("reason", list(ContentRestriction))
async def test_gallery_assets_do_not_override_paid_content_restrictions(
    tmp_path: Path, reason: ContentRestriction
) -> None:
    warning = f"Framefetch {reason.value}".encode() + b"\n" + WARNING
    with pytest.raises(RunnerFailure) as caught:
        await commands(tmp_path, gallery(), warning).inspect(URL, tmp_path)
    assert caught.value.code == "content_protected"


@pytest.mark.parametrize("reason", list(ContentRestriction))
@pytest.mark.parametrize(
    "payload",
    [
        gallery(),
        {"id": "123", "url": "https://cdn.example/video.mp4"},
        {
            "id": "123",
            "formats": [{"url": "https://cdn.example/video.mp4", "has_drm": False}],
        },
        {"_type": "playlist", "entries": [gallery()]},
        {
            "_type": "playlist",
            "entries": [{"id": "123", "url": "https://cdn.example/video.mp4"}],
        },
        {
            "_type": "playlist",
            "entries": [{"id": "123", "url": "https://cdn.example/image.webp"}],
        },
        {
            "id": "123",
            "media_type": "image",
            "thumbnails": [{"url": "https://cdn.example/image.webp"}],
        },
    ],
    ids=[
        "gallery",
        "direct",
        "formats",
        "gallery-entry",
        "video-entry",
        "photos",
        "thumbnail",
    ],
)
async def test_content_restrictions_precede_drm_and_other_warnings_on_all_assets(
    tmp_path: Path, reason: ContentRestriction, payload: dict
) -> None:
    warning = (
        b"This format is DRM protected\nHTTP Error 429\nThis video requires login\n"
        + f"Framefetch {reason.value}".encode()
    )
    with pytest.raises(RunnerFailure) as caught:
        await commands(tmp_path, payload, warning).inspect(URL, tmp_path)
    assert caught.value.code == "content_protected"
    assert caught.value.status == 422
    assert caught.value.failure.stage == "resolve"


@pytest.mark.parametrize(
    "warning,expected,status",
    [
        (b"Only the preview will be extracted", "content_protected", 422),
        (b"This is a supporter-only video", "content_protected", 422),
        (b"Members-only content", "content_unavailable", 403),
        (b"This video is private", "content_unavailable", 403),
        (b"This video has been deleted", "content_unavailable", 422),
    ],
)
async def test_clear_gallery_cannot_override_explicit_content_warnings(
    tmp_path: Path, warning: bytes, expected: str, status: int
) -> None:
    # The DRM rule appears before membership/private rules in the rule table.
    warning = b"This format is DRM protected\n" + warning + b"\nHTTP Error 429"
    with pytest.raises(RunnerFailure) as caught:
        await commands(tmp_path, gallery(), warning).inspect(
            "https://www.bilibili.com/video/BV13x41117TL", tmp_path
        )
    assert caught.value.code == expected
    assert caught.value.status == status


@pytest.mark.parametrize("reason", list(ContentRestriction))
@pytest.mark.parametrize(
    "payload",
    [
        {"_type": "playlist", "entries": []},
        {"_type": "playlist", "entries": [None]},
        {"_type": "playlist", "entries": [{"_type": "playlist", "entries": []}]},
    ],
    ids=["empty", "invalid-member", "nested"],
)
async def test_content_restriction_precedes_collection_validation(
    tmp_path: Path, reason: ContentRestriction, payload: dict
) -> None:
    with pytest.raises(RunnerFailure) as caught:
        await commands(
            tmp_path, payload, f"Framefetch {reason.value}".encode()
        ).inspect(URL, tmp_path)
    assert caught.value.code == "content_protected"
    assert caught.value.status == 422


@pytest.mark.parametrize(
    "assets", [None, [], {}, [None], [{}], [{"url": None}], [{"url": "  "}]]
)
async def test_empty_or_malformed_assets_do_not_suppress_warning(
    tmp_path: Path, assets: object
) -> None:
    with pytest.raises(RunnerFailure) as caught:
        await commands(tmp_path, {**gallery(), "assets": assets}).inspect(URL, tmp_path)
    assert caught.value.code == "extractor_broken"


async def test_unknown_media_kind_cannot_use_gallery_assets(tmp_path: Path) -> None:
    with pytest.raises(RunnerFailure) as caught:
        await commands(tmp_path, {**gallery(), "media_kind": "unknown"}).inspect(
            URL, tmp_path
        )
    assert caught.value.code == "extractor_broken"


@pytest.mark.parametrize("url", ["http://127.0.0.1/image.jpg", "file:///image.jpg"])
async def test_gallery_urls_still_pass_through_source_validation(
    tmp_path: Path, url: str
) -> None:
    raw = {**gallery(), "assets": [{"url": url}]}
    payload = await commands(tmp_path, raw).inspect(URL, tmp_path)
    with pytest.raises(RunnerFailure) as caught:
        normalize_for_settings(payload, settings(tmp_path))
    assert caught.value.code == "invalid_inspection_response"


async def test_single_photo_metadata_survives_no_video_warning(tmp_path: Path) -> None:
    payload = {
        "id": "123",
        "title": "Photo",
        "extractor_key": "Instagram",
        "media_type": "image",
        "formats": [],
        "thumbnails": [{"url": "https://cdn.example.com/full.jpg", "width": 1080}],
    }
    parsed = await commands(
        tmp_path, payload, b"There is no video in this post"
    ).inspect("https://www.instagram.com/p/example/", tmp_path)
    inspection = normalize_for_settings(parsed, settings(tmp_path))
    assert inspection.media_kind is MediaKind.IMAGE_GALLERY
    assert inspection.asset_count == 1
