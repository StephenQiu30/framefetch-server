from __future__ import annotations

from copy import deepcopy

import pytest
from app.services.downloads.rules.enums import (
    AudioCodecFamily,
    Container,
    MediaKind,
    StreamKind,
    VideoCodecFamily,
)
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.metadata import (
    build_download_options,
    collection_fallback_assets,
    enrich_direct_metadata,
    enrich_format_metadata,
    normalize_metadata,
    normalize_selected_format_metadata,
)


@pytest.mark.parametrize(
    "avg,nominal,expected",
    [("0/0", "25/1", 25), ("30000/1001", "25/1", 30000 / 1001), ("0/0", "0/0", None)],
)
def test_sparse_prefix_uses_valid_rate_without_guessing(avg, nominal, expected):
    enriched = enrich_format_metadata(
        {"format_id": "clear-prefix"},
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 640,
                    "height": 360,
                    "avg_frame_rate": avg,
                    "r_frame_rate": nominal,
                }
            ]
        },
    )
    if expected is None:
        assert enriched["fps"] is None
    else:
        assert enriched["fps"] == pytest.approx(expected)


def media_info() -> dict[str, object]:
    return {
        "id": "controlled-video",
        "title": "Controlled fixture",
        "duration": 60.5,
        "extractor_key": "Controlled",
        "webpage_url_domain": "media.example.com",
        "live_status": "not_live",
        "formats": [
            {
                "format_id": "muxed-1080",
                "ext": "mp4",
                "width": 1920,
                "height": 1080,
                "fps": 29.97,
                "vcodec": "avc1.640028",
                "acodec": "mp4a.40.2",
                "language": "zh-CN",
                "tbr": 2500,
                "filesize": 20_000_000,
            },
            {
                "format_id": "video-720",
                "ext": "webm",
                "width": 1280,
                "height": 720,
                "fps": 60,
                "vcodec": "vp09.00.40.08",
                "acodec": "none",
            },
            {
                "format_id": "audio-opus",
                "ext": "webm",
                "vcodec": "none",
                "acodec": "opus",
                "language": "en",
                "abr": 128,
            },
        ],
    }


def gallery_info() -> dict[str, object]:
    return {
        "id": "controlled-note",
        "title": "官方图文作品",
        "extractor_key": "DouyinNote",
        "media_kind": "image_gallery",
        "assets": [
            {
                "url": "https://images.example.com/one.jpeg",
                "extension": "jpeg",
                "width": 1080,
                "height": 1440,
            },
            {
                "url": "https://images.example.com/two.webp",
                "extension": "webp",
            },
        ],
    }


def test_normalizes_public_image_gallery_assets() -> None:
    inspection = normalize_metadata(
        gallery_info(),
        max_duration_seconds=7200,
        max_candidate_streams=200,
        max_gallery_assets=10,
    )

    assert inspection.media_kind is MediaKind.IMAGE_GALLERY
    assert inspection.duration_seconds == 0
    assert inspection.streams == ()
    assert inspection.asset_count == 2
    assert inspection.thumbnail_url == "https://images.example.com/one.jpeg"
    assert inspection.gallery_assets[0].extension == "jpg"
    assert inspection.gallery_assets[0].width == 1080


def test_normalizes_playlist_as_a_video_collection() -> None:
    payload = {
        "_type": "playlist",
        "id": "playlist-1",
        "title": "多个视频",
        "extractor_key": "Instagram",
        "entries": [{"id": "video-1"}, {"id": "video-2"}],
    }

    inspection = normalize_metadata(
        payload,
        max_duration_seconds=7200,
        max_candidate_streams=200,
        max_gallery_assets=10,
    )

    assert inspection.media_kind is MediaKind.VIDEO_COLLECTION
    assert inspection.duration_seconds == 0
    assert inspection.asset_count == 2
    assert inspection.streams == ()


def test_keeps_metadata_only_video_collection_zip_capable() -> None:
    payload = {
        "_type": "playlist",
        "id": "playlist-without-media",
        "title": "没有可播放格式的合集",
        "extractor_key": "Instagram",
        "entries": [
            {"id": "video-1", "formats": []},
            {"id": "video-2", "formats": []},
        ],
    }

    inspection = normalize_metadata(
        payload,
        max_duration_seconds=7200,
        max_candidate_streams=200,
        max_gallery_assets=10,
    )

    assert inspection.media_kind is MediaKind.VIDEO_COLLECTION
    assert inspection.asset_count == 2


def test_extracts_image_fallback_assets_from_metadata_only_carousel() -> None:
    payload = {
        "_type": "playlist",
        "id": "image-carousel",
        "title": "图文合集",
        "extractor_key": "Instagram",
        "entries": [
            {
                "id": "image-1",
                "thumbnail": "https://cdn.example.com/image-1.webp?regular_photo=1",
            },
            {
                "id": "image-2",
                "thumbnail": "https://cdn.example.com/image-2.webp?regular_photo=1",
            },
        ],
    }

    assets = collection_fallback_assets(payload)

    assert [asset.extension for asset in assets] == ["webp", "webp"]
    assert [asset.url for asset in assets] == [
        "https://cdn.example.com/image-1.webp?regular_photo=1",
        "https://cdn.example.com/image-2.webp?regular_photo=1",
    ]

    inspection = normalize_metadata(
        payload,
        max_duration_seconds=7200,
        max_candidate_streams=200,
        max_gallery_assets=10,
    )

    assert inspection.media_kind is MediaKind.IMAGE_GALLERY
    assert inspection.asset_count == 2
    assert inspection.gallery_assets == assets


def test_rejects_gallery_assets_over_configured_limit() -> None:
    payload = gallery_info()
    assets = payload["assets"]
    assert isinstance(assets, list)
    assets.extend(assets)

    with pytest.raises(RunnerFailure) as caught:
        normalize_metadata(
            payload,
            max_duration_seconds=7200,
            max_candidate_streams=200,
            max_gallery_assets=2,
        )

    assert caught.value.code == "format_limit_exceeded"


def test_rejects_gallery_asset_with_private_url() -> None:
    payload = gallery_info()
    assets = payload["assets"]
    assert isinstance(assets, list)
    assets[0] = {"url": "http://127.0.0.1/private", "extension": "jpg"}

    with pytest.raises(RunnerFailure) as caught:
        normalize_metadata(
            payload,
            max_duration_seconds=7200,
            max_candidate_streams=200,
        )

    assert caught.value.code == "invalid_inspection_response"


def test_normalizes_ytdlp_formats_into_domain_streams_and_options() -> None:
    payload = media_info()
    payload["thumbnail"] = "https://images.example.com/cover.webp"
    inspection = normalize_metadata(
        payload,
        max_duration_seconds=7200,
        max_candidate_streams=200,
    )

    assert inspection.title == "Controlled fixture"
    assert inspection.provider_media_id == "controlled-video"
    assert inspection.extractor_key == "Controlled"
    assert inspection.duration_seconds == 60.5
    assert inspection.thumbnail_url == "https://images.example.com/cover.webp"
    assert inspection.thumbnail_urls == ("https://images.example.com/cover.webp",)
    assert len(inspection.streams) == 3
    muxed, video, audio = inspection.streams
    assert muxed.kind is StreamKind.MUXED
    assert muxed.container is Container.MP4
    assert muxed.video_codec_family is VideoCodecFamily.H264
    assert muxed.audio_codec_family is AudioCodecFamily.AAC
    assert video.kind is StreamKind.VIDEO
    assert video.video_codec_family is VideoCodecFamily.VP9
    assert audio.kind is StreamKind.AUDIO
    assert audio.audio_codec_family is AudioCodecFamily.OPUS

    options = build_download_options(inspection.streams, max_options=20)
    assert {(item.height, item.container_preference.value) for item in options} == {
        (1080, "mp4"),
        (720, "webm"),
    }


def test_image_scrubber_format_does_not_become_a_download_option() -> None:
    payload = media_info()
    formats = payload["formats"]
    assert isinstance(formats, list)
    formats.insert(
        0,
        {
            "format_id": "scrubber_hd",
            "ext": "jpg",
            "width": 320,
            "height": 180,
            "vcodec": "unknown",
            "acodec": "none",
        },
    )

    inspection = normalize_metadata(
        payload,
        max_duration_seconds=7200,
        max_candidate_streams=200,
    )
    options = build_download_options(inspection.streams, max_options=20)

    assert options
    assert all(option.hints.video_id != "scrubber_hd" for option in options)


def test_silent_video_becomes_a_download_option() -> None:
    payload = media_info()
    payload["formats"] = [
        {
            "format_id": "silent",
            "ext": "mp4",
            "width": 640,
            "height": 360,
            "fps": 30,
            "vcodec": "h264",
            "acodec": "none",
        }
    ]

    inspection = normalize_metadata(
        payload,
        max_duration_seconds=7200,
        max_candidate_streams=200,
    )
    options = build_download_options(inspection.streams, max_options=20)

    assert len(options) == 1
    assert options[0].audio_codec_family is AudioCodecFamily.NONE
    assert options[0].hints.audio_id is None


def test_incompatible_audio_does_not_hide_a_silent_video_option() -> None:
    payload = media_info()
    payload["formats"] = [
        {
            "format_id": "silent",
            "ext": "mp4",
            "width": 640,
            "height": 360,
            "fps": 30,
            "vcodec": "h264",
            "acodec": "none",
        },
        {
            "format_id": "unsupported-audio",
            "ext": "mp3",
            "vcodec": "none",
            "acodec": "mp3",
        },
    ]

    inspection = normalize_metadata(
        payload,
        max_duration_seconds=7200,
        max_candidate_streams=200,
    )
    options = build_download_options(inspection.streams, max_options=20)

    assert len(options) == 1
    assert options[0].audio_codec_family is AudioCodecFamily.NONE
    assert options[0].hints.video_id == "silent"
    assert options[0].hints.audio_id is None


def test_top_level_selected_format_becomes_one_semantic_candidate() -> None:
    payload = {
        "id": "spotlight-id",
        "title": "Spotlight",
        "duration": 4.665,
        "extractor_key": "SnapchatSpotlight",
        "format_id": "0",
        "ext": "mp4",
        "url": "https://cdn.example.com/spotlight.mp4",
        "requested_downloads": [{"filename": "ignored.mp4"}],
    }

    normalized = normalize_selected_format_metadata(payload)

    assert normalized["formats"] == [
        {
            "format_id": "0",
            "ext": "mp4",
            "url": "https://cdn.example.com/spotlight.mp4",
        }
    ]
    assert "formats" not in payload


def test_existing_format_list_is_preserved_by_selected_format_normalization() -> None:
    payload = {"formats": [{"format_id": "720p"}], "format_id": "selected"}

    assert normalize_selected_format_metadata(payload) is payload


def test_ignores_unsafe_thumbnail_urls() -> None:
    payload = media_info()
    payload["thumbnail"] = "http://127.0.0.1/private-cover"

    inspection = normalize_metadata(
        payload,
        max_duration_seconds=7200,
        max_candidate_streams=200,
    )

    assert inspection.thumbnail_url is None


def test_keeps_safe_thumbnail_fallbacks_in_priority_order() -> None:
    payload = media_info()
    payload["thumbnail"] = "https://images.example.com/preferred.webp"
    payload["thumbnails"] = [
        {"url": "http://127.0.0.1/private-cover"},
        {"url": "https://images.example.com/fallback-small.jpg"},
        {"url": "https://images.example.com/fallback-large.jpg"},
        {"url": "https://images.example.com/preferred.webp"},
    ]

    inspection = normalize_metadata(
        payload,
        max_duration_seconds=7200,
        max_candidate_streams=200,
    )

    assert inspection.thumbnail_urls == (
        "https://images.example.com/preferred.webp",
        "https://images.example.com/fallback-large.jpg",
        "https://images.example.com/fallback-small.jpg",
    )


def test_enriches_sparse_direct_media_with_ffprobe_metadata() -> None:
    payload = {
        "id": "sample",
        "title": "sample",
        "extractor_key": "Generic",
        "direct": True,
        "formats": [{"format_id": "mp4", "ext": "mp4"}],
    }
    probe = {
        "format": {"duration": "3.704", "size": "409785", "bit_rate": "885064"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 640,
                "height": 360,
                "avg_frame_rate": "30/1",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "tags": {"language": "und"},
            },
        ],
    }

    inspection = normalize_metadata(
        enrich_direct_metadata(payload, probe),
        max_duration_seconds=7200,
        max_candidate_streams=200,
    )

    assert inspection.duration_seconds == 3.704
    assert inspection.streams[0].kind is StreamKind.MUXED
    assert inspection.streams[0].height == 360
    assert inspection.streams[0].fps == 30


def test_enriches_single_sparse_provider_format_with_ffprobe_metadata() -> None:
    raw = {
        "format_id": "http-832",
        "ext": "mp4",
        "url": "https://cdn.example.com/video.mp4",
    }
    probe = {
        "format": {"size": "409785", "bit_rate": "885064"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 640,
                "height": 360,
                "avg_frame_rate": "30000/1001",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "tags": {"language": "en"},
            },
        ],
    }

    enriched = enrich_format_metadata(raw, probe)

    assert enriched["vcodec"] == "h264"
    assert enriched["acodec"] == "aac"
    assert enriched["width"] == 640
    assert enriched["height"] == 360
    assert enriched["fps"] == pytest.approx(29.97, rel=0.001)
    assert enriched["dynamic_range"] == "SDR"
    assert enriched["language"] == "en"
    assert enriched["filesize"] == "409785"
    assert enriched["tbr"] == pytest.approx(885.064)


def test_nominal_clip_rate_is_opt_in_and_preserves_material_average_difference():
    probe = {
        "streams": [
            {
                "codec_type": "video",
                "avg_frame_rate": "4613120/153687",
                "r_frame_rate": "30/1",
            }
        ]
    }
    assert enrich_format_metadata({}, probe)["fps"] > 30.01
    assert enrich_format_metadata({}, probe, prefer_nominal_fps=True)["fps"] == 30
    probe["streams"][0]["avg_frame_rate"] = "25/1"
    assert enrich_format_metadata({}, probe, prefer_nominal_fps=True)["fps"] == 25


def test_ignores_sub_unit_provider_metrics_after_integer_normalization() -> None:
    payload = media_info()
    formats = payload["formats"]
    assert isinstance(formats, list)
    first = formats[0]
    assert isinstance(first, dict)
    first["tbr"] = 0.248

    inspection = normalize_metadata(
        payload,
        max_duration_seconds=7200,
        max_candidate_streams=200,
    )

    assert inspection.streams[0].bitrate_kbps is None


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"_type": "playlist", "entries": []}, "unsupported_source"),
        ({"is_live": True}, "unsupported_source"),
        ({"live_status": "is_upcoming"}, "unsupported_source"),
        ({"has_drm": True}, "unsupported_source"),
        ({"duration": 7201}, "duration_limit_exceeded"),
        ({"duration": None}, "unsupported_source"),
    ],
)
def test_rejects_unsupported_media_metadata(
    change: dict[str, object],
    code: str,
) -> None:
    payload = deepcopy(media_info())
    payload.update(change)

    with pytest.raises(RunnerFailure) as caught:
        normalize_metadata(
            payload,
            max_duration_seconds=7200,
            max_candidate_streams=200,
        )

    assert caught.value.code == code


@pytest.mark.parametrize(
    "provider_id",
    ["x" * 129, "video\n1080", "video\n", "video+audio", "-video"],
)
def test_rejects_unsafe_provider_format_identifier(provider_id: str) -> None:
    payload = media_info()
    formats = payload["formats"]
    assert isinstance(formats, list)
    first = formats[0]
    assert isinstance(first, dict)
    first["format_id"] = provider_id

    with pytest.raises(RunnerFailure) as caught:
        normalize_metadata(
            payload,
            max_duration_seconds=7200,
            max_candidate_streams=200,
        )

    assert caught.value.code == "invalid_inspection_response"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "x" * 257),
        ("id", "media\nidentity"),
        ("extractor_key", "x" * 129),
        ("extractor_key", "Controlled\x7f"),
    ],
)
def test_rejects_unsafe_media_identity(field: str, value: str) -> None:
    payload = media_info()
    payload[field] = value

    with pytest.raises(RunnerFailure) as caught:
        normalize_metadata(
            payload,
            max_duration_seconds=7200,
            max_candidate_streams=200,
        )

    assert caught.value.code == "invalid_inspection_response"


@pytest.mark.parametrize(
    "representation",
    [
        {"url": "https://cdn.example.com/original.png"},
        {"media_type": "image", "thumbnail": "https://cdn.example.com/asset?id=1"},
        {
            "formats": [
                {
                    "url": "https://cdn.example.com/asset",
                    "ext": "webp",
                    "format_id": "original",
                }
            ]
        },
    ],
)
def test_single_image_uses_archive_without_video_fields(representation: dict) -> None:
    payload = {
        "id": "photo",
        "title": "Photo",
        "extractor_key": "Generic",
        **representation,
    }
    inspection = normalize_metadata(
        payload, max_duration_seconds=7200, max_candidate_streams=200
    )
    assert inspection.media_kind is MediaKind.IMAGE_GALLERY
    assert inspection.asset_count == 1
    assert not inspection.streams


def test_image_formats_in_playlist_are_not_video_formats() -> None:
    payload = {
        "id": "photos",
        "title": "Photos",
        "extractor_key": "Generic",
        "_type": "playlist",
        "entries": [
            {"url": "https://cdn.example.com/one.jpg", "format_id": "original"},
            {
                "formats": [
                    {
                        "url": "https://cdn.example.com/two.png",
                        "format_id": "original",
                        "ext": "png",
                    }
                ]
            },
        ],
    }
    inspection = normalize_metadata(
        payload, max_duration_seconds=7200, max_candidate_streams=200
    )
    assert inspection.media_kind is MediaKind.IMAGE_GALLERY
    assert inspection.asset_count == 2


@pytest.mark.parametrize(
    "declaration", [{"duration": 30}, {"media_type": "video"}, {"is_video": True}]
)
def test_video_poster_is_never_an_image_download(declaration: dict) -> None:
    payload = {
        "entries": [
            {
                "thumbnail": "https://cdn.example.com/cover.jpg",
                "is_video": False,
                **declaration,
            }
        ]
    }
    assert collection_fallback_assets(payload) == ()


def test_collection_never_drops_missing_members() -> None:
    with pytest.raises(RunnerFailure, match="invalid inspection response"):
        normalize_metadata(
            {"_type": "playlist", "entries": [{"id": "first"}, None]},
            max_duration_seconds=7200,
            max_candidate_streams=200,
        )
