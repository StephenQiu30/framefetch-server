from app.workers.runner.metadata import normalize_metadata
from app.workers.runner.plugins.yt_dlp_plugins.extractor.instagram_media import (
    _InstagramMediaIE,
)
from yt_dlp import YoutubeDL


def test_photo_identity_survives_provider_extraction_without_url_markers() -> None:
    extractor = _InstagramMediaIE(YoutubeDL({"quiet": True}))
    payload = extractor._extract_product(
        {
            "pk": "123",
            "media_type": 1,
            "title": "Public photo",
            "image_versions2": {
                "candidates": [
                    {
                        "url": "https://cdn.example.com/full.jpg",
                        "width": 2000,
                        "height": 1600,
                    },
                    {
                        "url": "https://cdn.example.com/small.jpg",
                        "width": 200,
                        "height": 160,
                    },
                ]
            },
        },
        get_comments=False,
    )
    payload["extractor_key"] = "Instagram"
    inspection = normalize_metadata(
        payload, max_duration_seconds=7200, max_candidate_streams=200
    )
    assert inspection.media_kind.value == "image_gallery"
    assert inspection.asset_count == 1
    assert inspection.gallery_assets[0].url == "https://cdn.example.com/full.jpg"


def test_unresolved_video_is_not_a_photo() -> None:
    extractor = _InstagramMediaIE(YoutubeDL({"quiet": True}))
    result = extractor._extract_product_media(
        {
            "pk": "123",
            "media_type": 2,
            "image_versions2": {
                "candidates": [{"url": "https://cdn.example.com/cover.jpg"}]
            },
        }
    )
    assert result["media_type"] == "video"


async def test_photo_pipeline_skips_video_probes_and_downloads_zip(tmp_path) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from zipfile import ZipFile

    from app.workers.runner.gallery import download_gallery_zip
    from app.workers.runner.inspection_pipeline import RunnerInspectionPipeline
    from app.workers.runner.provider_registry import provider_request
    from app.workers.runner.workspace import WorkspaceManager
    from helpers import settings

    extractor = _InstagramMediaIE(YoutubeDL({"quiet": True}))
    payload = extractor._extract_product(
        {
            "pk": "123",
            "media_type": 1,
            "title": "Photo",
            "image_versions2": {
                "candidates": [{"url": "https://cdn.example.com/photo.jpg"}]
            },
        },
        get_comments=False,
    )
    payload["extractor_key"] = "Instagram"
    commands = AsyncMock()
    commands.inspect.return_value = payload

    async def download(_url, output, _cwd, **_kwargs):
        output.write_bytes(b"\xff\xd8\xff" + b"synthetic fixture")

    commands.download_public_asset.side_effect = download
    workspace = WorkspaceManager(tmp_path / "runner").create("single-photo")
    try:
        inspection = await RunnerInspectionPipeline(
            settings(tmp_path), commands
        ).inspect(
            provider_request("https://www.instagram.com/p/example/"),
            workspace,
            context=SimpleNamespace(
                provider_key="instagram",
                identity_used=False,
            ),
            cookie_jar=None,
        )
        commands.probe_remote.assert_not_called()
        commands.download_probe_sample.assert_not_called()
        output = workspace.path / "artifact.zip"
        count = await download_gallery_zip(
            inspection.gallery_assets,
            output,
            workspace,
            title=inspection.title,
            referer="https://www.instagram.com/p/example/",
            commands=commands,
            max_asset_bytes=1024,
            max_assets=10,
        )
        assert count == 1
        with ZipFile(output) as archive:
            assert "images/0001.jpg" in archive.namelist()
    finally:
        workspace.cleanup()
