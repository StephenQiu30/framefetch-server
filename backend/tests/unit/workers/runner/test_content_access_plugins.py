from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.workers.runner.plugins.yt_dlp_plugins.extractor._content_access import (
    enforce_douyin_access,
)
from app.workers.runner.plugins.yt_dlp_plugins.extractor.bilibili_access import (
    _BiliBiliAccessIE,
)
from app.workers.runner.plugins.yt_dlp_plugins.extractor.douyin_note import (
    DouyinNoteIE,
    _find_item,
)
from app.workers.runner.plugins.yt_dlp_plugins.extractor.douyin_share import (
    _DouyinSharePageIE,
    _router_item,
)
from yt_dlp import YoutubeDL
from yt_dlp.utils import ExtractorError


@pytest.fixture(autouse=True)
def offline_visitor_session(monkeypatch: pytest.MonkeyPatch) -> None:
    # Visitor initialization has its own tests; these exercise page parsing.
    for module in ("douyin_share", "douyin_note"):
        monkeypatch.setattr(
            f"app.workers.runner.plugins.yt_dlp_plugins.extractor.{module}"
            ".ensure_visitor_cookies",
            lambda *_args: None,
        )


@pytest.mark.parametrize(
    ("item", "reason"),
    [
        ({"charge_info": {"is_charge_content": True}}, "content_paid_only"),
        (
            {"charge_info": {"is_charge_content": 1, "has_paid": 1}},
            "content_export_required",
        ),
        (
            {"chargeInfo": {"isChargeContent": "1", "hasPaid": "1"}},
            "content_export_required",
        ),
        ({"preview_config": {"is_preview": True}}, "content_preview_only"),
        (
            {"chargeInfo": {"isChargeContent": 1, "previewConfig": {"isPreview": 1}}},
            "content_preview_only",
        ),
        ({"charge_info": []}, "content_access_metadata_invalid"),
        (
            {"charge_info": {"is_charge_content": "unknown"}},
            "content_access_metadata_invalid",
        ),
    ],
)
def test_douyin_raw_restrictions(item, reason) -> None:
    with pytest.raises(ExtractorError, match=f"FrameFetch {reason}"):
        enforce_douyin_access(item)


@pytest.mark.parametrize(
    "item",
    [
        {},
        {"charge_info": None},
        {"chargeInfo": {"isChargeContent": 0}},
        {"preview_config": {"is_preview": "0"}},
    ],
)
def test_public_metadata_without_restrictions_is_unchanged(item) -> None:
    enforce_douyin_access(item)


@pytest.mark.parametrize("key", ["videoData", "videoInfo"])
def test_bilibili_original_state_rejects_supporters_before_normalization(key) -> None:
    extractor = _BiliBiliAccessIE(YoutubeDL({"quiet": True}))
    webpage = "window.__INITIAL_STATE__=" + json.dumps(
        {key: {"is_upower_exclusive": True}}
    )
    with pytest.raises(ExtractorError, match="content_supporter_only"):
        extractor._search_json(
            r"window\.__INITIAL_STATE__\s*=", webpage, "initial state", "BV1xx"
        )


def test_bilibili_free_state_is_preserved() -> None:
    extractor = _BiliBiliAccessIE(YoutubeDL({"quiet": True}))
    data = {"videoData": {"is_upower_exclusive": False}}
    assert (
        extractor._search_json(
            r"window\.__INITIAL_STATE__\s*=",
            "window.__INITIAL_STATE__=" + json.dumps(data),
            "initial state",
            "BV1xx",
        )
        == data
    )


@pytest.mark.parametrize(
    "data", [{"accept_description": ["高清", "试看"]}, {"is_preview": 1}]
)
def test_bilibili_preview_formats_cannot_escape(data) -> None:
    with pytest.raises(ExtractorError, match="content_preview_only"):
        _BiliBiliAccessIE().extract_formats(data)


def test_bilibili_real_extractor_calls_guard_before_further_network(
    monkeypatch,
) -> None:
    extractor = _BiliBiliAccessIE(YoutubeDL({"quiet": True}))
    url = "https://www.bilibili.com/video/BV1xx411c7mD"
    page = 'window.__INITIAL_STATE__={"videoData":{"is_upower_exclusive":true}};'
    monkeypatch.setattr(
        extractor,
        "_download_webpage_handle",
        lambda *a, **k: (page, SimpleNamespace(url=url)),
    )
    with pytest.raises(ExtractorError, match="content_supporter_only"):
        extractor._real_extract(url)


def test_douyin_upstream_parser_is_guarded() -> None:
    with pytest.raises(ExtractorError, match="content_paid_only"):
        _DouyinSharePageIE()._parse_aweme_video_app(
            {"charge_info": {"is_charge_content": True}}
        )


def test_paid_router_item_without_video_does_not_fall_back() -> None:
    item = {"aweme_id": "123", "charge_info": {"is_charge_content": True}}
    payload = {"loaderData": {"video": {"videoInfoRes": {"item_list": [item]}}}}
    with pytest.raises(ExtractorError, match="content_paid_only"):
        _router_item(payload, "123")


def test_douyin_note_does_not_export_paid_images(monkeypatch) -> None:
    extractor = DouyinNoteIE()
    item = {
        "charge_info": {"is_charge_content": True},
        "images": [{"url_list": ["https://example.com/image.jpg"]}],
    }
    monkeypatch.setattr(extractor, "_slides_item", lambda *a: item)
    with pytest.raises(ExtractorError, match="content_paid_only"):
        extractor._real_extract("https://www.douyin.com/note/1234567890123456789")


def test_note_wrapper_restriction_survives_unwrapping() -> None:
    with pytest.raises(ExtractorError, match="content_paid_only"):
        _find_item(
            {
                "aweme_id": "123",
                "charge_info": {"is_charge_content": 1},
                "note_info": {},
            },
            "123",
        )


def test_plugin_loads_in_standalone_ytdlp_process(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[4]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--verbose",
            "--plugin-dirs",
            str(root / "app/workers/runner"),
            "--simulate",
            "--",
            "file:///disabled",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert "personal_video (YoukuIE)" in completed.stderr
    assert "personal_video (VQQVideoIE)" in completed.stderr
    assert "content_access (BiliBiliIE)" in completed.stderr
    assert "share_page (DouyinIE)" in completed.stderr
    assert "Error while importing" not in completed.stderr
