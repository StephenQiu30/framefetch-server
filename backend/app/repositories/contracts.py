"""Primitive persistence contracts; domain and SQLAlchemy remain decoupled."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ArtifactCreate:
    bucket: str
    sha256: str
    size_bytes: int
    duration_ms: int
    container: str
    content_type: str
    media_metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class JobSourceSnapshot:
    job_id: UUID
    inspection_id: UUID
    owner_hash: str
    thumbnail_available: bool
    semantic_plan: dict[str, Any]
    provider_hints: dict[str, Any]
    extractor_key: str
    provider_media_id: str
    duration_seconds: int
    execution_context: dict[str, Any]
    url_ciphertext: bytes
    url_nonce: bytes
    url_key_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class DownloadThumbnailCandidateSnapshot:
    job_id: UUID
    owner_hash: str
    object_key: str


@dataclass(frozen=True, slots=True)
class OutboxSnapshot:
    id: UUID
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    payload: dict[str, Any]
    publish_attempts: int
    available_at: datetime
    created_at: datetime
