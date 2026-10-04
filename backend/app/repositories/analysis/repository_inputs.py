"""Read-only projections for immutable analysis inputs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.sql.elements import ColumnElement

from app.models import ArtifactRow, DocumentArtifactRow, DocumentRow, DownloadJobRow
from app.repositories.analysis.repository_mapping import analysis_artifact_snapshot
from app.repositories.repository_base import RepositoryBase
from app.services.analysis.input_models import (
    AnalysisDocumentSnapshot,
    AnalysisDocumentTextSource,
)
from app.services.analysis.models import AnalysisArtifactSnapshot
from app.services.analysis_execution.models import (
    AnalysisScreenplaySource,
    ScreenplaySceneSource,
)


class AnalysisInputRepository(RepositoryBase):
    async def get_artifact_for_download(
        self, download_id: UUID
    ) -> AnalysisArtifactSnapshot | None:
        return await self._artifact_projection(ArtifactRow.job_id == download_id)

    async def get_artifact(self, artifact_id: UUID) -> AnalysisArtifactSnapshot | None:
        return await self._artifact_projection(ArtifactRow.id == artifact_id)

    async def _artifact_projection(
        self, criterion: ColumnElement[bool]
    ) -> AnalysisArtifactSnapshot | None:
        async with self._sessions() as session:
            result = (
                await session.execute(
                    select(ArtifactRow, DownloadJobRow)
                    .join(DownloadJobRow, DownloadJobRow.id == ArtifactRow.job_id)
                    .where(criterion, ArtifactRow.deleted_at.is_(None))
                )
            ).one_or_none()
            if result is None:
                return None
            artifact, download = result
            return analysis_artifact_snapshot(artifact, download)

    async def get_document_for_analysis(
        self, document_id: UUID
    ) -> AnalysisDocumentSnapshot | None:
        async with self._sessions() as session:
            result = (
                await session.execute(
                    select(DocumentRow, DocumentArtifactRow)
                    .outerjoin(
                        DocumentArtifactRow,
                        and_(
                            DocumentArtifactRow.document_id == DocumentRow.id,
                            DocumentArtifactRow.kind == "normalized",
                        ),
                    )
                    .where(
                        DocumentRow.id == document_id,
                        DocumentRow.deleted_at.is_(None),
                    )
                )
            ).one_or_none()
            if result is None:
                return None
            document, normalized = result
            return AnalysisDocumentSnapshot(
                id=document.id,
                owner_hash=document.owner_hash,
                status=document.status,
                text_sha256=document.text_sha256,
                normalized_status=None if normalized is None else normalized.status,
                normalized_sha256=None if normalized is None else normalized.sha256,
                character_count=document.character_count,
            )

    async def get_document_text_source(
        self, document_id: UUID, owner_hash: str
    ) -> AnalysisDocumentTextSource | None:
        async with self._sessions() as session:
            result = (
                await session.execute(
                    select(DocumentRow, DocumentArtifactRow)
                    .join(
                        DocumentArtifactRow,
                        DocumentArtifactRow.document_id == DocumentRow.id,
                    )
                    .where(
                        DocumentRow.id == document_id,
                        DocumentRow.owner_hash == owner_hash,
                        DocumentRow.status == "ready",
                        DocumentRow.deleted_at.is_(None),
                        DocumentArtifactRow.kind == "normalized",
                        DocumentArtifactRow.status == "ready",
                        DocumentArtifactRow.deleted_at.is_(None),
                    )
                )
            ).one_or_none()
            if result is None:
                return None
            document, artifact = result
            if (
                document.text_sha256 != artifact.sha256
                or document.character_count is None
            ):
                return None
            return AnalysisDocumentTextSource(
                document.id,
                document.owner_hash,
                artifact.bucket,
                artifact.object_key,
                artifact.sha256,
                artifact.size_bytes,
                document.character_count,
            )

    async def get_screenplay_source(
        self, document_id: UUID, now: datetime
    ) -> AnalysisScreenplaySource | None:
        async with self._sessions() as session:
            result = (
                await session.execute(
                    select(DocumentRow, DocumentArtifactRow)
                    .join(
                        DocumentArtifactRow,
                        DocumentArtifactRow.document_id == DocumentRow.id,
                    )
                    .where(
                        DocumentRow.id == document_id,
                        DocumentRow.status == "ready",
                        DocumentRow.deleted_at.is_(None),
                        DocumentArtifactRow.kind == "normalized",
                        DocumentArtifactRow.status == "ready",
                        DocumentArtifactRow.deleted_at.is_(None),
                    )
                )
            ).one_or_none()
            if result is None:
                return None
            document, artifact = result
            if (
                document.character_count is None
                or document.detected_language is None
                or artifact.content_type != "text/markdown; charset=utf-8"
            ):
                raise ValueError("screenplay source metadata is incomplete")
            return AnalysisScreenplaySource(
                artifact_id=artifact.id,
                document_id=document.id,
                owner_hash=document.owner_hash,
                bucket=artifact.bucket,
                object_key=artifact.object_key,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                character_count=document.character_count,
                detected_language=document.detected_language,
                scenes=_screenplay_scenes(artifact.artifact_metadata),
            )


def _screenplay_scenes(metadata: object) -> tuple[ScreenplaySceneSource, ...]:
    allowed_keys = {"scenes", "parse_summary"}
    if (
        not isinstance(metadata, dict)
        or "scenes" not in metadata
        or not set(metadata).issubset(allowed_keys)
    ):
        raise ValueError("screenplay artifact metadata is invalid")
    values = metadata["scenes"]
    if not isinstance(values, list):
        raise ValueError("screenplay scene metadata is invalid")
    scenes: list[ScreenplaySceneSource] = []
    for value in values:
        if not isinstance(value, dict) or set(value) != {
            "id",
            "start",
            "end",
            "elements",
        }:
            raise ValueError("screenplay scene metadata is invalid")
        if not isinstance(value["elements"], list):
            raise ValueError("screenplay element metadata is invalid")
        scenes.append(
            ScreenplaySceneSource(
                id=value["id"],
                start=value["start"],
                end=value["end"],
            )
        )
    return tuple(scenes)
