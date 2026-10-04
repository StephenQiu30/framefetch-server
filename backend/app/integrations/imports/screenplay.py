from __future__ import annotations

from pathlib import Path

from app.integrations.imports.docx import DocxScreenplayVerifier
from app.integrations.imports.pdf import PdfScreenplayVerifier
from app.integrations.imports.text import TextScreenplayVerifier
from app.services.import_execution.errors import ImportVerificationRejected
from app.services.import_execution.models import (
    ImportVerificationClaim,
    VerifiedDocumentImport,
)
from app.services.imports.rules.enums import ImportErrorCode, ImportSourceFormat

_TEXT_FORMATS = {
    ImportSourceFormat.TXT,
    ImportSourceFormat.MARKDOWN,
    ImportSourceFormat.FOUNTAIN,
    ImportSourceFormat.SRT,
    ImportSourceFormat.VTT,
}


class ScreenplayImportVerifier:
    def __init__(
        self,
        text: TextScreenplayVerifier,
        docx: DocxScreenplayVerifier,
        pdf: PdfScreenplayVerifier,
    ) -> None:
        self._text = text
        self._docx = docx
        self._pdf = pdf

    async def __call__(
        self, path: Path, claim: ImportVerificationClaim
    ) -> VerifiedDocumentImport:
        if claim.source_format in _TEXT_FORMATS:
            return await self._text(path, claim)
        if claim.source_format is ImportSourceFormat.DOCX:
            return await self._docx(path, claim)
        if claim.source_format is ImportSourceFormat.PDF:
            return await self._pdf(path, claim)
        raise ImportVerificationRejected(
            ImportErrorCode.DOCUMENT_FORMAT_UNSUPPORTED,
            "document format verifier is not available",
        )
