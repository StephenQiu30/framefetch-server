"""Actual files from one saved revision; no inference and no account writes."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID

from app.services.creation.cards import (
    CardPage,
    CardRenderConfig,
    export_cards_zip,
    render_cards,
)
from app.services.creation.catalog import get_capability
from app.services.creation.exports import (
    ExportArtifact,
    ExportAsset,
    ExportDocument,
    export_csv,
    export_document,
)
from app.services.creation.models import CreationRevisionResponse, CreationTaskResponse
from app.services.creation.subtitles import SubtitleCue, export_subtitles


class CreationExportPersistence(Protocol):
    async def get_task(
        self, task_id: UUID, owner_hash: str | None = None
    ) -> CreationTaskResponse: ...
    async def get_task_revision(
        self, task_id: UUID, revision_id: UUID, owner_hash: str
    ) -> CreationRevisionResponse: ...
    async def task_materials(
        self, task_id: UUID, owner_hash: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def get_export(
        self, task_id: UUID, revision_id: UUID, format: str, owner_hash: str
    ) -> ExportArtifact | None: ...
    async def save_export(
        self,
        task_id: UUID,
        revision_id: UUID,
        format: str,
        owner_hash: str,
        artifact: ExportArtifact,
    ) -> ExportArtifact: ...


class CreationExportService:
    def __init__(
        self, repository: CreationExportPersistence, *, font_path: Path | None
    ) -> None:
        self.repository = repository
        self.font_path = font_path

    async def export(
        self, task_id: UUID, revision_id: UUID, format: str, owner_hash: str
    ) -> ExportArtifact:
        task = await self.repository.get_task(task_id, owner_hash)
        if format not in get_capability(task.skill_id).outputs:
            raise ValueError("this capability does not export that format")
        cached = await self.repository.get_export(
            task_id, revision_id, format, owner_hash
        )
        if cached is not None:
            return cached
        revision = await self.repository.get_task_revision(
            task_id, revision_id, owner_hash
        )
        materials = await self.repository.task_materials(task_id, owner_hash)
        assets: list[ExportAsset] = []
        images: dict[str, bytes] = {}
        for material in materials:
            if material["kind"] == "image":
                data = base64.b64decode(
                    str(material["image_data_base64"]), validate=True
                )
                images[str(material["id"])] = data
                metadata = material.get("data", {})
                media_type = str(metadata.get("image_media_type", "image/png"))
                extension = {
                    "image/png": "png",
                    "image/jpeg": "jpg",
                    "image/webp": "webp",
                }.get(media_type)
                if extension is None:
                    raise ValueError("unsupported actual image format")
                name = str(metadata.get("filename", f"{material['id']}.{extension}"))
                assets.append(
                    ExportAsset(
                        name, data, media_type, str(material["rights_statement"])
                    )
                )
        title = str(revision.data.get("title", get_capability(task.skill_id).name))
        document = ExportDocument(
            title,
            revision.text,
            str(revision_id),
            references=[
                {
                    "material_id": str(item["id"]),
                    "revision_id": str(item["revision_id"]),
                    "sha256": str(item["sha256"]),
                }
                for item in materials
            ],
            assets=assets,
        )
        render_data = dict(revision.data)
        if format in {"srt", "vtt"}:
            video = next((item for item in materials if item["kind"] == "video"), None)
            if video is None:
                raise ValueError("subtitle export needs its pinned source video")
            render_data["subtitle_source_duration_ms"] = video["source"]["duration_ms"]
        artifact = await asyncio.to_thread(
            self._render, document, render_data, format, images
        )
        if len(artifact.data) > 64 * 1024 * 1024:
            raise ValueError("export exceeds the 64 MiB resource limit")
        artifact = ExportArtifact(
            artifact.filename,
            artifact.media_type,
            artifact.data,
            {
                **artifact.metadata,
                "revision_sha256": revision.sha256,
                "confirmed": revision.confirmed,
                "stale": task.stale,
                "renderer_version": "2026-10-04",
            },
        )
        return await self.repository.save_export(
            task_id, revision_id, format, owner_hash, artifact
        )

    def _render(
        self,
        document: ExportDocument,
        data: dict[str, Any],
        format: str,
        images: dict[str, bytes],
    ) -> ExportArtifact:
        if format == "cards":
            if self.font_path is None:
                raise ValueError(
                    "configure a licensed local CJK font before rendering cards"
                )
            source_pages = data.get("pages")
            if not isinstance(source_pages, list) or not source_pages:
                raise ValueError("no saved card pages")
            pages: list[CardPage] = []
            for page in source_pages:
                if (
                    not isinstance(page, dict)
                    or not isinstance(page.get("title"), str)
                    or not isinstance(page.get("body"), str)
                ):
                    raise ValueError("invalid saved card page")
                image_id = page.get("image_material_id")
                if image_id is not None and str(image_id) not in images:
                    raise ValueError("card image is missing from pinned materials")
                pages.append(
                    CardPage(page["title"], page["body"], images.get(str(image_id)))
                )
            cards = render_cards(
                pages,
                CardRenderConfig(str(self.font_path)),
                revision_id=document.revision_id,
            )
            return export_cards_zip(
                cards,
                revision_id=document.revision_id,
                title=document.title,
                assets=document.assets,
                references=document.references,
            )
        if format in {"srt", "vtt"}:
            cues_data = data.get("cues")
            if not isinstance(cues_data, list) or not cues_data:
                raise ValueError("no saved subtitle cues")
            cues = [
                SubtitleCue(
                    start_ms=item["start_ms"], end_ms=item["end_ms"], text=item["text"]
                )
                for item in cues_data
            ]
            rendered = export_subtitles(
                cues,
                format=cast(Any, format),
                duration_ms=data.get("subtitle_source_duration_ms"),
            )
            return ExportArtifact(
                f"subtitles.{format}", "text/plain; charset=utf-8", rendered
            )
        if format == "csv":
            shots = data.get("shots")
            if isinstance(shots, list) and shots:
                return export_csv(
                    shots,
                    (
                        "id",
                        "start_ms",
                        "end_ms",
                        "observation",
                        "sound_annotation",
                        "confirmed",
                        "boundary_kind",
                    ),
                )
            structured = data.get("structured", {})
            findings = (
                structured.get("findings") if isinstance(structured, dict) else None
            )
            if not isinstance(findings, list) or not findings:
                raise ValueError("no saved analysis findings to export")
            return export_csv(
                [
                    {
                        "id": item["id"],
                        "category": item["category"],
                        "description": item["description"],
                        "impact": item["impact"],
                        "suggestion": item["suggestion"],
                        "evidence_indices": str(item["evidence_indices"]),
                        "media_evidence_indices": str(item["media_evidence_indices"]),
                    }
                    for item in findings
                ],
                (
                    "id",
                    "category",
                    "description",
                    "impact",
                    "suggestion",
                    "evidence_indices",
                    "media_evidence_indices",
                ),
            )
        return export_document(document, cast(Any, format))
