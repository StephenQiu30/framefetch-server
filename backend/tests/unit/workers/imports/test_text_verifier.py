from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

import pytest
from app.integrations.imports.text import (
    TextScreenplayVerifier,
    TextVerificationSettings,
)
from app.services.import_execution.errors import ImportVerificationRejected
from app.services.import_execution.models import ImportVerificationClaim
from app.services.imports.rules.enums import (
    ContentKind,
    ImportErrorCode,
    ImportSourceFormat,
)

RESOURCE_ID = UUID("11111111-1111-4111-8111-111111111111")


@pytest.mark.parametrize(
    "source_format", [ImportSourceFormat.MARKDOWN, ImportSourceFormat.TXT]
)
async def test_markdown_structure_summary_matches_reader_without_counting_code(
    tmp_path: Path, source_format: ImportSourceFormat
) -> None:
    content = (
        "# 标题\n\n"
        "章节\n---\n\n"
        "> ## 引用中的标题\n\n"
        "- 项目一\n  - 嵌套项目\n\n"
        "| 项目 | 内容 |\n| --- | --- |\n| 时长 | 五秒 |\n\n"
        "```markdown\n# 示例标题\n- 示例列表\n"
        "| 示例 | 表格 |\n| --- | --- |\n| A | B |\n```\n"
    ).encode()
    workspace = tmp_path / "markdown"
    workspace.mkdir()
    source = workspace / "source"
    source.write_bytes(content)
    result = await TextScreenplayVerifier(
        tmp_path,
        TextVerificationSettings(
            max_size_bytes=4096, max_characters=4096, max_line_characters=200
        ),
    )(source, claim(content, source_format))

    assert result.normalized_path.read_bytes() == content
    assert result.normalized_sha256 == hashlib.sha256(content).hexdigest()
    assert result.scenes == ()
    assert result.parse_summary.heading_count == (
        3 if source_format is ImportSourceFormat.MARKDOWN else 0
    )
    assert result.parse_summary.table_count == (
        1 if source_format is ImportSourceFormat.MARKDOWN else 0
    )
    if source_format is ImportSourceFormat.MARKDOWN:
        assert result.parse_summary.list_item_count == 2


def claim(content: bytes, source_format: ImportSourceFormat) -> ImportVerificationClaim:
    return ImportVerificationClaim(
        resource_id=RESOURCE_ID,
        content_kind=ContentKind.SCREENPLAY,
        source_format=source_format,
        attempt=1,
        version=2,
        object_key=f"quarantine/screenplay/{RESOURCE_ID}/1/source",
        declared_size_bytes=len(content),
        declared_sha256=hashlib.sha256(content).hexdigest(),
    )


def verifier(root: Path) -> TextScreenplayVerifier:
    return TextScreenplayVerifier(
        root,
        TextVerificationSettings(
            max_size_bytes=1024, max_characters=100, max_line_characters=40
        ),
    )


@pytest.mark.parametrize(
    "source_format",
    [ImportSourceFormat.TXT, ImportSourceFormat.MARKDOWN, ImportSourceFormat.FOUNTAIN],
)
async def test_text_formats_are_verified_and_written_as_canonical_utf8(
    tmp_path: Path, source_format: ImportSourceFormat
) -> None:
    workspace = tmp_path / "task-random"
    workspace.mkdir()
    content = "\ufeffINT. ROOM - DAY\r\nCafé\r\n".encode()
    source = workspace / "source"
    source.write_bytes(content)

    verified = await verifier(tmp_path)(source, claim(content, source_format))

    assert verified.original_sha256 == hashlib.sha256(content).hexdigest()
    assert verified.normalized_path.read_text(encoding="utf-8") == (
        "INT. ROOM - DAY\nCafé\n"
    )
    assert (
        verified.normalized_sha256
        == hashlib.sha256(verified.normalized_path.read_bytes()).hexdigest()
    )
    assert verified.scenes == ()
    assert verified.parse_summary.page_count is None
    assert verified.parse_summary.paragraph_count == 2
    assert verified.parse_summary.heading_count == 0


@pytest.mark.parametrize(
    ("content", "error_code"),
    [
        (b"not utf8: \xff", ImportErrorCode.DOCUMENT_TEXT_UNAVAILABLE),
        (b"INT. ROOM\nNUL:\x00", ImportErrorCode.DOCUMENT_TEXT_UNAVAILABLE),
        (b"x" * 41, ImportErrorCode.DOCUMENT_TEXT_UNAVAILABLE),
        (b"x\n" * 51, ImportErrorCode.DOCUMENT_TEXT_UNAVAILABLE),
    ],
)
async def test_invalid_encoding_controls_and_long_lines_fail_closed(
    tmp_path: Path, content: bytes, error_code: ImportErrorCode
) -> None:
    workspace = tmp_path / "task-random"
    workspace.mkdir()
    source = workspace / "source"
    source.write_bytes(content)

    with pytest.raises(ImportVerificationRejected) as raised:
        await verifier(tmp_path)(source, claim(content, ImportSourceFormat.TXT))

    assert raised.value.code is error_code


async def test_hash_mismatch_and_unsupported_document_format_are_rejected(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "task-random"
    workspace.mkdir()
    content = b"INT. ROOM - DAY\nText\n"
    source = workspace / "source"
    source.write_bytes(content)
    wrong_hash = claim(content, ImportSourceFormat.TXT)
    wrong_hash = ImportVerificationClaim(
        resource_id=wrong_hash.resource_id,
        content_kind=wrong_hash.content_kind,
        source_format=wrong_hash.source_format,
        attempt=wrong_hash.attempt,
        version=wrong_hash.version,
        object_key=wrong_hash.object_key,
        declared_size_bytes=wrong_hash.declared_size_bytes,
        declared_sha256="0" * 64,
    )

    with pytest.raises(ImportVerificationRejected) as mismatch:
        await verifier(tmp_path)(source, wrong_hash)
    with pytest.raises(ImportVerificationRejected) as unsupported:
        await verifier(tmp_path)(source, claim(content, ImportSourceFormat.DOCX))

    assert mismatch.value.code is ImportErrorCode.SHA256_MISMATCH
    assert unsupported.value.code is ImportErrorCode.DOCUMENT_FORMAT_UNSUPPORTED


@pytest.mark.parametrize(
    "source_format",
    [
        ImportSourceFormat.TXT,
        ImportSourceFormat.MARKDOWN,
        ImportSourceFormat.SRT,
        ImportSourceFormat.VTT,
    ],
)
async def test_ordinary_article_and_subtitle_import_need_no_scene(
    tmp_path, source_format
):
    content = "文章观点。\r\n  保留缩进与空格  \r\n".encode()
    workspace = tmp_path / "ordinary"
    workspace.mkdir()
    source = workspace / "source"
    source.write_bytes(content)
    result = await verifier(tmp_path)(source, claim(content, source_format))
    assert result.scenes == ()
    assert result.character_count > 0
    assert result.normalized_path.read_text() == "文章观点。\n  保留缩进与空格  \n"
    assert result.normalized_path.name == "document.md"
