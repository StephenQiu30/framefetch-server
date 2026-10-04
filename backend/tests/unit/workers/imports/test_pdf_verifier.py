from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from app.integrations.imports.pdf import PdfScreenplayVerifier, PdfVerificationSettings
from app.integrations.imports.text import TextVerificationSettings
from app.services.import_execution.errors import ImportVerificationRejected
from app.services.import_execution.models import ImportVerificationClaim
from app.services.imports.rules.enums import (
    ContentKind,
    ImportErrorCode,
    ImportSourceFormat,
)
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    RectangleObject,
    TextStringObject,
)

DOCUMENT_ID = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")


def _writer_with_pages(*texts: str) -> PdfWriter:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
        )
        if text:
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            operations = (
                "BT /F1 12 Tf 72 720 Td "
                + " 0 -20 Td ".join(f"({line}) Tj" for line in escaped.splitlines())
                + " ET"
            )
            stream = DecodedStreamObject()
            stream.set_data(operations.encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
    return writer


def _bytes(writer: PdfWriter) -> bytes:
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _claim(content: bytes) -> ImportVerificationClaim:
    return ImportVerificationClaim(
        resource_id=DOCUMENT_ID,
        content_kind=ContentKind.SCREENPLAY,
        source_format=ImportSourceFormat.PDF,
        attempt=1,
        version=2,
        object_key=f"quarantine/screenplay/{DOCUMENT_ID}/1/source",
        declared_size_bytes=len(content),
        declared_sha256=hashlib.sha256(content).hexdigest(),
    )


def _settings(**overrides: int | float) -> PdfVerificationSettings:
    values: dict[str, int | float] = {
        "max_pages": 10,
        "max_page_content_bytes": 100_000,
        "max_total_content_bytes": 200_000,
        "max_inspected_objects": 1_000,
        "min_text_characters": 20,
        "min_text_page_ratio": 0.8,
        "max_replacement_character_ratio": 0.01,
    }
    values.update(overrides)
    return PdfVerificationSettings(
        text=TextVerificationSettings(
            max_size_bytes=2 * 1024**2,
            max_characters=10_000,
            max_line_characters=1_000,
        ),
        **values,
    )


async def _verify(
    tmp_path: Path,
    content: bytes,
    settings: PdfVerificationSettings | None = None,
):
    workspace = tmp_path / "task-random"
    workspace.mkdir(exist_ok=True)
    source = workspace / "source"
    source.write_bytes(content)
    verifier = PdfScreenplayVerifier(tmp_path, settings or _settings())
    return await verifier(source, _claim(content))


async def test_pdf_extracts_text_into_shared_screenplay_contract(
    tmp_path: Path,
) -> None:
    content = _bytes(
        _writer_with_pages(
            "INT. ROOM - DAY\nALICE\nHello there, this is a complete scene.",
            "EXT. STREET - NIGHT\nBOB\nWe should leave before midnight.",
        )
    )

    verified = await _verify(tmp_path, content)

    normalized = verified.normalized_path.read_text(encoding="utf-8")
    assert "INT. ROOM - DAY\nALICE" in normalized
    assert "EXT. STREET - NIGHT\nBOB" in normalized
    assert verified.detected_language == "en-US"
    assert verified.scenes == ()
    assert verified.parse_summary.page_count == 2
    assert verified.parse_summary.paragraph_count == 6
    assert verified.parse_summary.heading_count == 0
    assert verified.parse_summary.dialogue_block_count == 0


@pytest.mark.parametrize("kind", ["javascript", "attachment", "uri", "external-stream"])
async def test_pdf_active_external_and_embedded_content_is_rejected(
    tmp_path: Path, kind: str
) -> None:
    writer = _writer_with_pages(
        "INT. ROOM - DAY\nALICE\nThis scene contains enough ordinary text."
    )
    if kind == "javascript":
        writer.add_js("app.alert('no')")
    elif kind == "attachment":
        writer.add_attachment("payload.txt", b"forbidden")
    elif kind == "uri":
        writer.add_uri(0, "https://example.invalid", RectangleObject((0, 0, 10, 10)))
    else:
        stream = writer.pages[0].raw_get("/Contents").get_object()
        stream[NameObject("/F")] = TextStringObject("outside.dat")

    with pytest.raises(ImportVerificationRejected) as raised:
        await _verify(tmp_path, _bytes(writer))

    assert raised.value.code is ImportErrorCode.DOCUMENT_STRUCTURE_INVALID


async def test_encrypted_pdf_is_rejected_without_password_attempt(
    tmp_path: Path,
) -> None:
    writer = _writer_with_pages(
        "INT. ROOM - DAY\nALICE\nThis encrypted scene must not be opened."
    )
    writer.encrypt("secret")

    with pytest.raises(ImportVerificationRejected) as raised:
        await _verify(tmp_path, _bytes(writer))

    assert raised.value.code is ImportErrorCode.DOCUMENT_ENCRYPTED


@pytest.mark.parametrize(
    ("content", "settings", "error"),
    [
        (b"not a PDF", _settings(), ImportErrorCode.DOCUMENT_STRUCTURE_INVALID),
        (
            _bytes(_writer_with_pages("")),
            _settings(),
            ImportErrorCode.DOCUMENT_TEXT_UNAVAILABLE,
        ),
        (
            _bytes(_writer_with_pages("only one text page", "", "")),
            _settings(min_text_page_ratio=0.8),
            ImportErrorCode.DOCUMENT_TEXT_UNAVAILABLE,
        ),
        (
            _bytes(_writer_with_pages("one", "two")),
            _settings(max_pages=1),
            ImportErrorCode.DOCUMENT_STRUCTURE_INVALID,
        ),
    ],
)
async def test_pdf_invalid_scanned_low_quality_and_capacity_cases_fail_closed(
    tmp_path: Path,
    content: bytes,
    settings: PdfVerificationSettings,
    error: ImportErrorCode,
) -> None:
    with pytest.raises(ImportVerificationRejected) as raised:
        await _verify(tmp_path, content, settings)

    assert raised.value.code is error


async def test_pdf_content_stream_budget_is_enforced_before_text_extraction(
    tmp_path: Path,
) -> None:
    content = _bytes(
        _writer_with_pages(
            "INT. ROOM - DAY\nALICE\nThis content stream is deliberately over budget."
        )
    )

    with pytest.raises(ImportVerificationRejected) as raised:
        await _verify(tmp_path, content, _settings(max_page_content_bytes=10))

    assert raised.value.code is ImportErrorCode.DOCUMENT_STRUCTURE_INVALID
