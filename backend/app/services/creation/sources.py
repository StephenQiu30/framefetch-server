"""Read-only local document extraction with explicit resource and format limits."""

from __future__ import annotations

from io import BytesIO
from pathlib import PurePath
from zipfile import BadZipFile, ZipFile

from docx import Document
from pypdf import PdfReader

MAX_TEXT_CHARACTERS = 30000
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


def extract_document(filename: str, data: bytes, *, kind: str) -> str:
    if not data or len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("document is empty or exceeds the 10 MiB input limit")
    suffix = PurePath(filename).suffix.casefold()
    if suffix in {".txt", ".md", ".fountain", ".srt", ".vtt"}:
        text = data.decode("utf-8-sig", errors="strict")
    elif suffix == ".docx":
        try:
            with ZipFile(BytesIO(data)) as archive:
                if (
                    len(archive.infolist()) > 1000
                    or sum(item.file_size for item in archive.infolist())
                    > 40 * 1024 * 1024
                    or any(item.flag_bits & 1 for item in archive.infolist())
                ):
                    raise ValueError("DOCX archive resource limit")
        except BadZipFile as error:
            raise ValueError("invalid DOCX") from error
        document = Document(BytesIO(data))
        # Walk paragraphs and tables in source order, not all tables at the end.
        blocks: list[str] = []
        for block in document.iter_inner_content():
            if hasattr(block, "text"):
                blocks.append(block.text)
            else:
                blocks.extend(
                    "\t".join(cell.text for cell in row.cells) for row in block.rows
                )
        text = "\n\n".join(blocks)
    elif suffix == ".pdf":
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted or len(reader.pages) > 200:
            raise ValueError("encrypted or oversized PDF is unsupported")
        chunks: list[str] = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
            if sum(len(chunk) for chunk in chunks) > MAX_TEXT_CHARACTERS:
                raise ValueError("document exceeds 30000 Unicode characters")
        text = "\n\n".join(chunks)
        if not text.strip():
            raise ValueError("PDF has no extractable text; OCR is not supported")
    else:
        raise ValueError("unsupported document format")
    if not text.strip() or "\x00" in text or len(text) > MAX_TEXT_CHARACTERS:
        raise ValueError("invalid text or exceeds 30000 Unicode characters")
    if kind == "script":
        import re

        count = len(
            re.findall(
                r"(?m)^\s*(?:INT\.|EXT\.|INT/EXT\.|内[.．景]|外[.．景]|第.{1,8}场)",
                text,
            )
        )
        if count > 60:
            raise ValueError("script exceeds 60 scenes")
    return text
