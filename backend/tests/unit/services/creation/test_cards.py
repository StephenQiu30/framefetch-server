from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import cast
from zipfile import ZipFile

import pytest
from app.services.creation.cards import (
    CardPage,
    CardRenderConfig,
    export_cards_zip,
    render_cards,
)
from app.services.creation.export_service import (
    CreationExportPersistence,
    CreationExportService,
)
from app.services.creation.exports import ExportAsset, ExportDocument
from PIL import Image, ImageChops


@pytest.fixture
def font_path() -> str:
    # Explicit fixture font, never a production font discovery policy.
    configured = os.environ.get("TEST_CREATION_FONT_PATH")
    candidates = (
        [configured]
        if configured
        else [
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    pytest.skip("需要显式本地测试字体；生产缺字体必须失败")


def test_actual_pngs_autopaginate_keep_all_text_and_original_image(
    font_path: str,
) -> None:
    picture = BytesIO()
    Image.new("RGB", (120, 60), "red").save(picture, "PNG")
    original = picture.getvalue()
    body = "中文内容 English 123。" * 60
    if "DejaVu" in font_path:
        body = "English content 123. " * 60
    title = "原创卡片" if "DejaVu" not in font_path else "Original"
    cards = render_cards(
        [CardPage(title, body, original)],
        CardRenderConfig(
            font_path, width=640, height=800, font_size=28, margin=40, max_pages=20
        ),
        revision_id="revision-4",
    )
    assert len(cards) > 1
    assert "".join(line for card in cards for line in card.lines) == body
    assert [card.index for card in cards] == list(range(1, len(cards) + 1))
    for card in cards:
        with Image.open(BytesIO(card.data)) as image:
            image.load()
            assert image.format == "PNG" and image.size == (640, 800)
            changed = ImageChops.difference(
                image, Image.new("RGB", image.size, "white")
            ).getbbox()
            assert changed is not None
            assert (
                0 < changed[0]
                and 0 < changed[1]
                and changed[2] < 640
                and changed[3] < 800
            )
        assert card.metadata["revision_id"] == "revision-4"
        assert card.metadata["kind"] == "local_template"
        assert card.metadata["sha256"] == hashlib.sha256(card.data).hexdigest()
    assert picture.getvalue() == original


def test_jpeg_opens_and_page_edits_change_only_new_output(font_path: str) -> None:
    config = CardRenderConfig(
        font_path, image_format="JPEG", width=640, height=800, margin=40, font_size=28
    )
    before = render_cards([CardPage("Original", "English paragraph")], config)[0]
    after = render_cards([CardPage("Original", "Changed paragraph")], config)[0]
    assert before.data != after.data and before.lines == ("English paragraph",)
    with Image.open(BytesIO(after.data)) as image:
        image.load()
        assert image.format == "JPEG"


def test_missing_fonts_bad_assets_and_page_budget_fail_without_images(
    font_path: str,
) -> None:
    with pytest.raises(ValueError, match="字体"):
        render_cards(
            [CardPage("Original", "Content")], CardRenderConfig("/no/such/font.ttf")
        )
    config = CardRenderConfig(font_path, width=640, height=800, margin=40, font_size=28)
    with pytest.raises(ValueError, match="图片"):
        render_cards([CardPage("Original", "Content", b"not PNG")], config)
    with pytest.raises(ValueError, match="页数预算"):
        render_cards(
            [CardPage("Original", "Long text " * 1000)], replace(config, max_pages=1)
        )
    with pytest.raises(ValueError, match="未覆盖"):
        render_cards([CardPage("Original", "Missing " + chr(0x10FFFF))], config)


def test_long_title_and_overwide_glyph_do_not_silently_crop(font_path: str) -> None:
    config = CardRenderConfig(font_path, width=320, height=320, margin=32, font_size=64)
    with pytest.raises(ValueError, match="占满"):
        render_cards([CardPage("Title " * 100, "Body")], config)


def test_card_package_contains_real_images_editable_source_and_hashes(
    font_path: str,
) -> None:
    config = CardRenderConfig(font_path, width=640, height=800, margin=40, font_size=28)
    cards = render_cards([CardPage("Original", "Content")], config, revision_id="r3")
    package = export_cards_zip(cards, revision_id="r3")
    with ZipFile(BytesIO(package.data)) as archive:
        source = json.loads(archive.read("cards.json"))
        manifest = json.loads(archive.read("manifest.json"))
        assert source["revision_id"] == "r3"
        assert source["pages"][0]["body_lines"] == ["Content"]
        assert manifest["page_order"] == ["card-01.png"]
        for item in manifest["files"]:
            assert (
                hashlib.sha256(archive.read(item["path"])).hexdigest() == item["sha256"]
            )
        with Image.open(BytesIO(archive.read("assets/card-01.png"))) as image:
            image.load()
            assert image.size == (640, 800)
    with pytest.raises(ValueError, match="版本"):
        export_cards_zip(cards, revision_id="other-version")


def test_wrapped_lines_keep_punctuation_with_text_without_losing_content(
    font_path: str,
) -> None:
    body = (
        "abcde, fghij(klmno).pqrst" * 4
        if "DejaVu" in font_path
        else "甲乙丙丁戊，己庚辛壬（甲乙丙丁戊）己。" * 4
    )
    cards = render_cards(
        [CardPage("Example", body)],
        CardRenderConfig(font_path, width=320, height=800, margin=40, font_size=48),
        revision_id="punctuation-review",
    )
    lines = [line for card in cards for line in card.lines if line]
    assert len(lines) > 4
    assert "".join(lines) == body
    assert all(line[0] not in "，。、；：！？）》】’”.,;:!?)]}" for line in lines)
    assert all(line[-1] not in "（《【〔〈「『‘“([{" for line in lines)


def test_service_card_package_keeps_pinned_material_version_references(
    font_path: str,
) -> None:
    references = [
        {
            "material_id": "mother-material",
            "revision_id": "confirmed-source-version",
            "sha256": hashlib.sha256(b"Original mother text").hexdigest(),
        }
    ]
    service = CreationExportService(
        cast(CreationExportPersistence, object()), font_path=Path(font_path)
    )
    artifact = service._render(
        ExportDocument(
            "Cards", "Original mother text", "confirmed-card-version", references
        ),
        {"pages": [{"title": "Original", "body": "Original mother text"}]},
        "cards",
        {},
    )
    with ZipFile(BytesIO(artifact.data)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        source = json.loads(archive.read("cards.json"))
        assert manifest["references"] == references
        assert source["references"] == references
        assert source["revision_id"] == "confirmed-card-version"


def test_webp_source_renders_actual_png_and_retains_original_asset(
    font_path: str,
) -> None:
    picture = BytesIO()
    Image.new("RGB", (120, 60), "red").save(picture, "WEBP", lossless=True)
    original = picture.getvalue()
    service = CreationExportService(
        cast(CreationExportPersistence, object()), font_path=Path(font_path)
    )
    artifact = service._render(
        ExportDocument(
            "Cards",
            "Original content",
            "webp-version",
            assets=[ExportAsset("original.webp", original, "image/webp", "Original")],
        ),
        {
            "pages": [
                {
                    "title": "Original",
                    "body": "Content",
                    "image_material_id": "image-material",
                }
            ]
        },
        "cards",
        {"image-material": original},
    )
    with ZipFile(BytesIO(artifact.data)) as archive:
        assert archive.read("assets/original.webp") == original
        source = json.loads(archive.read("cards.json"))
        assert (
            source["pages"][0]["image_sha256"] == hashlib.sha256(original).hexdigest()
        )
        with Image.open(BytesIO(archive.read("assets/card-01.png"))) as image:
            image.load()
            assert image.format == "PNG" and image.size == (1080, 1440)
            colors = image.getcolors(image.width * image.height)
            assert colors is not None
            assert (
                sum(count for count, color in colors if color == (255, 0, 0))
                >= 120 * 60
            )
