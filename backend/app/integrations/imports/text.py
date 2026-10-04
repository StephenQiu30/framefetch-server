from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.integrations.imports.normalization import normalized_document
from app.integrations.imports.source import verified_source
from app.services.import_execution.errors import ImportVerificationRejected
from app.services.import_execution.models import (
    ImportVerificationClaim,
    VerifiedDocumentImport,
)
from app.services.imports.rules.enums import (
    ContentKind,
    ImportErrorCode,
    ImportSourceFormat,
)

_TEXT_FORMATS = {
    ImportSourceFormat.TXT,
    ImportSourceFormat.MARKDOWN,
    ImportSourceFormat.FOUNTAIN,
    ImportSourceFormat.SRT,
    ImportSourceFormat.VTT,
}


@dataclass(frozen=True, slots=True)
class TextVerificationSettings:
    max_size_bytes: int
    max_characters: int = 2_000_000
    max_line_characters: int = 20_000

    def __post_init__(self) -> None:
        if min(self.max_size_bytes, self.max_characters, self.max_line_characters) <= 0:
            raise ValueError("text verification limits must be positive")


class TextScreenplayVerifier:
    def __init__(
        self, workspace_root: Path, settings: TextVerificationSettings
    ) -> None:
        self._workspace_root = workspace_root.resolve()
        self._settings = settings

    async def __call__(
        self, path: Path, claim: ImportVerificationClaim
    ) -> VerifiedDocumentImport:
        if (
            claim.content_kind is not ContentKind.SCREENPLAY
            or claim.source_format not in _TEXT_FORMATS
        ):
            raise ImportVerificationRejected(
                ImportErrorCode.DOCUMENT_FORMAT_UNSUPPORTED,
                "unsupported text screenplay contract",
            )
        resolved, content, digest = verified_source(
            path,
            self._workspace_root,
            claim,
            max_size_bytes=self._settings.max_size_bytes,
            unsafe_code=ImportErrorCode.DOCUMENT_TEXT_UNAVAILABLE,
        )
        try:
            decoded = content.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise ImportVerificationRejected(
                ImportErrorCode.DOCUMENT_TEXT_UNAVAILABLE,
                "document is not valid UTF-8",
            ) from exc
        return normalized_document(
            resolved,
            claim,
            original_sha256=digest,
            original_size_bytes=len(content),
            extracted_text=decoded,
            limits=self._settings,
        )
