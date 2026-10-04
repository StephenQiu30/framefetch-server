from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AnalysisDocumentSnapshot:
    id: UUID
    owner_hash: str
    status: str
    text_sha256: str | None
    normalized_status: str | None
    normalized_sha256: str | None
    character_count: int | None = None


@dataclass(frozen=True, slots=True)
class AnalysisDocumentTextSource:
    document_id: UUID
    owner_hash: str
    bucket: str
    object_key: str
    sha256: str
    size_bytes: int
    character_count: int
