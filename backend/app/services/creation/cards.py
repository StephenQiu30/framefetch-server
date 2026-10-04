"""Local template cards with explicit fonts, measured wrapping and real images."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

from app.services.creation.exports import (
    ExportArtifact,
    ExportAsset,
    ExportDocument,
    export_zip,
)
from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True, slots=True)
class CardPage:
    title: str
    body: str
    image: bytes | None = None


@dataclass(frozen=True, slots=True)
class CardRenderConfig:
    font_path: str
    width: int = 1080
    height: int = 1440
    font_size: int = 48
    margin: int = 80
    max_pages: int = 20
    image_format: Literal["PNG", "JPEG"] = "PNG"
    fallback_font_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RenderedCard:
    index: int
    source_page: int
    filename: str
    data: bytes
    width: int
    height: int
    lines: tuple[str, ...]
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class _Glyph:
    text: str
    font: ImageFont.FreeTypeFont


_NO_LINE_START = frozenset("，。、；：！？）》】〕〉」』〗〙〛’”％%.,;:!?)]}")
_NO_LINE_END = frozenset("（《【〔〈「『〖〘〚‘“([{")


def _clusters(text: str) -> list[str]:
    clusters: list[str] = []
    for char in text:
        attached = unicodedata.combining(char) or char in ("\ufe0e", "\ufe0f", "\u200d")
        if clusters and (attached or clusters[-1].endswith("\u200d")):
            clusters[-1] += char
        else:
            clusters.append(char)
    return clusters


def _fonts(config: CardRenderConfig) -> list[ImageFont.FreeTypeFont]:
    if not config.font_path:
        raise ValueError("未配置本地中文字体；不会联网下载或静默替换字体")
    if len(config.fallback_font_paths) > 4:
        raise ValueError("最多配置四个备用字体")
    fonts = []
    for font_path in (config.font_path, *config.fallback_font_paths):
        path = Path(font_path)
        if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("配置的字体不存在或超过大小限制")
        try:
            fonts.append(ImageFont.truetype(str(path), config.font_size))
        except OSError as exc:
            raise ValueError("配置的字体无法按所选字号读取") from exc
    return fonts


def _glyph(text: str, fonts: Sequence[ImageFont.FreeTypeFont]) -> _Glyph:
    characters = [char for char in text if char not in ("\ufe0e", "\ufe0f", "\u200d")]
    for font in fonts:
        missing = bytes(font.getmask("\U0010ffff"))
        if all(
            char.isspace() or bytes(font.getmask(char)) != missing
            for char in characters
        ):
            return _Glyph(text, font)
    raise ValueError(f"配置的字体未覆盖字符 {text!r}；请补充有权使用的字体")


def _width(glyphs: Sequence[_Glyph]) -> float:
    return sum(_advance(glyph) for glyph in glyphs)


def _advance(glyph: _Glyph) -> float:
    left, _, right, _ = glyph.font.getbbox(glyph.text, anchor="lt")
    return max(glyph.font.getlength(glyph.text), float(right - min(left, 0)))


def _wrap(
    text: str, fonts: Sequence[ImageFont.FreeTypeFont], width: int
) -> list[list[_Glyph]]:
    result: list[list[_Glyph]] = []
    glyph_cache: dict[str, _Glyph] = {}
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        current: list[_Glyph] = []
        for cluster in _clusters(paragraph):
            if any(ord(char) < 32 for char in cluster):
                if cluster == "\t":
                    cluster = "    "
                else:
                    raise ValueError("卡片正文不能包含不可见控制字符")
            if cluster not in glyph_cache:
                glyph_cache[cluster] = _glyph(cluster, fonts)
            glyph = glyph_cache[cluster]
            if _width([glyph]) > width:
                raise ValueError("单个字符超过卡片可用宽度，请调整画布或字号")
            if current and _width([*current, glyph]) > width:
                following = [glyph]
                # Keep closing punctuation with its preceding text, and opening
                # punctuation with its following text. Preserve every cluster.
                while current and (
                    following[0].text[0] in _NO_LINE_START
                    or current[-1].text[-1] in _NO_LINE_END
                ):
                    following.insert(0, current.pop())
                if not current or _width(following) > width:
                    raise ValueError("相邻文字与标点超过可用宽度，请调整画布或字号")
                result.append(current)
                current = following
                continue
            current.append(glyph)
        result.append(current)
    return result


def _decode_image(content: bytes | None) -> Image.Image | None:
    if content is None:
        return None
    if not content or len(content) > 10 * 1024 * 1024:
        raise ValueError("卡片图片为空或超过 10 MiB")
    try:
        with Image.open(BytesIO(content)) as image:
            if (
                image.format not in ("PNG", "JPEG", "WEBP")
                or image.width * image.height > 20_000_000
                or getattr(image, "n_frames", 1) != 1
            ):
                raise ValueError("卡片图片格式或像素范围不支持")
            image.load()
            return image.convert("RGB")
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("卡片图片不能读取") from exc


def _line_height(fonts: Sequence[ImageFont.FreeTypeFont], font_size: int) -> int:
    maximum = max(sum(font.getmetrics()) for font in fonts)
    return max(maximum + 8, round(font_size * 1.5))


def _draw_line(
    draw: ImageDraw.ImageDraw, line: Sequence[_Glyph], x: float, y: int
) -> None:
    for glyph in line:
        draw.text((x, y), glyph.text, font=glyph.font, fill="#202020", anchor="lt")
        x += _advance(glyph)


def render_cards(
    pages: Sequence[CardPage], config: CardRenderConfig, *, revision_id: str = ""
) -> list[RenderedCard]:
    if (
        not 320 <= config.width <= 2160
        or not 320 <= config.height <= 2880
        or not 16 <= config.font_size <= 120
        or not 16 <= config.margin < min(config.width, config.height) // 3
        or not 1 <= config.max_pages <= 100
        or config.image_format not in ("PNG", "JPEG")
    ):
        raise ValueError("卡片画布、字号、边距或页数配置无效")
    if not pages or len(pages) > config.max_pages:
        raise ValueError("卡片源页数超过配置范围")
    if sum(len(page.title) + len(page.body) for page in pages) > 30_000:
        raise ValueError("卡片文本合计超过 30,000 字符")
    fonts = _fonts(config)
    font_hashes = [
        hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for path in (config.font_path, *config.fallback_font_paths)
    ]
    width = config.width - 2 * config.margin
    line_height = _line_height(fonts, config.font_size)
    rendered: list[RenderedCard] = []
    for source_page, page in enumerate(pages, 1):
        if not page.title.strip() or (not page.body.strip() and page.image is None):
            raise ValueError("卡片需要标题和正文或图片")
        title_lines = _wrap(page.title, fonts, width)
        body_lines = _wrap(page.body, fonts, width) if page.body else []
        picture = _decode_image(page.image)
        image_height = min(config.height // 3, 400) if picture is not None else 0
        title_height = len(title_lines) * line_height + line_height // 2
        top = config.margin + title_height + image_height
        if picture is not None:
            top += line_height // 2
        # Reserve the bottom margin and one line for the page number.
        capacity = (config.height - config.margin - line_height - top) // line_height
        if capacity < 1:
            raise ValueError("标题或图片占满画布，无法无裁切显示正文")
        chunks = [
            body_lines[i : i + capacity] for i in range(0, len(body_lines), capacity)
        ] or [[]]
        if len(rendered) + len(chunks) > config.max_pages:
            raise ValueError("自动分页超过页数预算；正文保留，请增加预算或缩小范围")
        for chunk in chunks:
            canvas = Image.new("RGB", (config.width, config.height), "white")
            draw = ImageDraw.Draw(canvas)
            y = config.margin
            for line in title_lines:
                _draw_line(draw, line, config.margin, y)
                y += line_height
            y += line_height // 2
            if picture is not None:
                image = picture.copy()
                image.thumbnail((width, image_height), Image.Resampling.LANCZOS)
                canvas.paste(image, (config.margin + (width - image.width) // 2, y))
                y += image_height + line_height // 2
            for line in chunk:
                _draw_line(draw, line, config.margin, y)
                y += line_height
            index = len(rendered) + 1
            footer = f"{index:02}"
            draw.text(
                (config.margin, config.height - config.margin - line_height),
                footer,
                font=fonts[0],
                fill="#666666",
                anchor="lt",
            )
            stream = BytesIO()
            canvas.save(stream, format=config.image_format, quality=92)
            data = stream.getvalue()
            extension = "png" if config.image_format == "PNG" else "jpg"
            lines = tuple("".join(glyph.text for glyph in line) for line in chunk)
            rendered.append(
                RenderedCard(
                    index,
                    source_page,
                    f"card-{index:02}.{extension}",
                    data,
                    config.width,
                    config.height,
                    lines,
                    {
                        "revision_id": revision_id,
                        "source_title": page.title,
                        "source_page": source_page,
                        "body_lines": list(lines),
                        "font_sha256": font_hashes,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "image_sha256": hashlib.sha256(page.image).hexdigest()
                        if page.image
                        else None,
                        "kind": "local_template",
                        "image_format": config.image_format,
                    },
                )
            )
    return rendered


def export_cards_zip(
    cards: Sequence[RenderedCard],
    *,
    revision_id: str,
    title: str = "小红书卡片",
    assets: Sequence[ExportAsset] = (),
    references: Sequence[Mapping[str, object]] = (),
) -> ExportArtifact:
    if not cards or len(cards) > 100 or not revision_id.strip():
        raise ValueError("卡片包需要实际图片和确认版本")
    sources: list[dict[str, object]] = []
    pictures: list[ExportAsset] = []
    for expected_index, card in enumerate(cards, 1):
        if (
            card.index != expected_index
            or card.metadata.get("revision_id") != revision_id
        ):
            raise ValueError("卡片页序或确认版本不一致")
        image = _decode_image(card.data)
        if image is None or image.size != (card.width, card.height):
            raise ValueError("卡片图片与尺寸声明不一致")
        media_type = "image/png" if card.filename.endswith(".png") else "image/jpeg"
        pictures.append(
            ExportAsset(
                card.filename,
                card.data,
                media_type,
                "本地模板输出；原始素材及字体许可由任务准入另行记录",
            )
        )
        sources.append(
            {
                "index": card.index,
                "source_page": card.source_page,
                "title": card.metadata.get("source_title", ""),
                "body_lines": list(card.lines),
                "image": f"assets/{card.filename}",
                "width": card.width,
                "height": card.height,
                "sha256": hashlib.sha256(card.data).hexdigest(),
                "font_sha256": card.metadata.get("font_sha256", []),
                "image_sha256": card.metadata.get("image_sha256"),
            }
        )
    body = "\n\n".join(
        f"## {item['index']}. {item['title']}\n\n"
        + "\n".join(cards[index].lines)
        + f"\n\n![第 {item['index']} 页]({item['image']})"
        for index, item in enumerate(sources)
    )
    base = export_zip(
        ExportDocument(
            title,
            body,
            revision_id,
            references=references,
            assets=[*pictures, *assets],
        )
    )
    with ZipFile(BytesIO(base.data)) as source_archive:
        files = {name: source_archive.read(name) for name in source_archive.namelist()}
    source = json.dumps(
        {"revision_id": revision_id, "references": list(references), "pages": sources},
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    files["cards.json"] = source
    manifest = json.loads(files["manifest.json"])
    manifest["files"].append(
        {
            "path": "cards.json",
            "sha256": hashlib.sha256(source).hexdigest(),
            "size": len(source),
        }
    )
    manifest["page_order"] = [card.filename for card in cards]
    manifest["kind"] = "local_template"
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode(
        "utf-8"
    )
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    data = stream.getvalue()
    return ExportArtifact(
        "cards.zip",
        "application/zip",
        data,
        {
            "revision_id": revision_id,
            "sha256": hashlib.sha256(data).hexdigest(),
            "page_count": len(cards),
            "kind": "local_template",
        },
    )
