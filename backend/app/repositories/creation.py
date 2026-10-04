"""Atomic PostgreSQL creation facts; model calls stay outside transactions."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import as_utc, utc_now
from app.models.ai_provider import AiProviderProfileRow
from app.models.analysis_worker import AnalysisWorkerHeartbeatRow
from app.models.creation import (
    CreationExportRow,
    CreationMaterialRow,
    CreationProjectRow,
    CreationRevisionRow,
    CreationTaskRow,
)
from app.models.document import DocumentArtifactRow, DocumentRow
from app.models.download import ArtifactRow, DownloadJobRow
from app.models.outbox import OutboxEventRow
from app.repositories.analysis.worker_registry import ANALYSIS_MESSAGE_SCHEMA_VERSION
from app.repositories.repository_base import RepositoryBase
from app.services.creation.errors import creation_error
from app.services.creation.exports import ExportArtifact
from app.services.creation.models import (
    CreationConfirmRequest,
    CreationMaterialCreateRequest,
    CreationMaterialResponse,
    CreationProjectCreateRequest,
    CreationProjectResponse,
    CreationRevisionResponse,
    CreationRevisionSaveRequest,
    CreationTaskCreateRequest,
    CreationTaskResponse,
    CreationUsage,
)


def content_digest(text_value: str, data: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"text": text_value, "data": data},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class CreationRepository(RepositoryBase):
    async def create_project(
        self, owner_hash: str, key: str, request: CreationProjectCreateRequest
    ) -> CreationProjectResponse:
        digest = _request_digest(request.model_dump(mode="json"))
        async with self._sessions() as session, session.begin():
            await _lock_owner(session, owner_hash)
            row = await session.scalar(
                select(CreationProjectRow).where(
                    CreationProjectRow.owner_hash == owner_hash,
                    CreationProjectRow.idempotency_key == key,
                )
            )
            if row is not None:
                _same_request(row.request_sha256, digest)
                return CreationProjectResponse.model_validate(row)
            row = CreationProjectRow(
                id=uuid4(),
                owner_hash=owner_hash,
                idempotency_key=key,
                request_sha256=digest,
                title=request.title,
                description=request.description,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(row)
            await session.flush()
            return CreationProjectResponse.model_validate(row)

    async def list_projects(
        self, owner_hash: str, limit: int = 50
    ) -> tuple[CreationProjectResponse, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(CreationProjectRow)
                .where(CreationProjectRow.owner_hash == owner_hash)
                .order_by(CreationProjectRow.created_at.desc())
                .limit(limit)
            )
            return tuple(CreationProjectResponse.model_validate(row) for row in rows)

    async def create_material(
        self,
        owner_hash: str,
        key: str,
        request: CreationMaterialCreateRequest,
        *,
        file_bytes: bytes | None = None,
        text_value: str | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> CreationMaterialResponse:
        digest = _request_digest(request.model_dump(mode="json"))
        async with self._sessions() as session, session.begin():
            await _lock_owner(session, owner_hash)
            existing = await session.scalar(
                select(CreationMaterialRow).where(
                    CreationMaterialRow.owner_hash == owner_hash,
                    CreationMaterialRow.idempotency_key == key,
                )
            )
            if existing is not None:
                _same_request(existing.request_sha256, digest)
                return await _material_view(session, existing)
            await _require_project(session, request.project_id, owner_hash)
            artifact = await self._require_artifact(session, request, owner_hash)
            if request.document_id is not None:
                await self._require_document(session, request.document_id, owner_hash)
            source_revision = None
            if request.source_revision_id is not None:
                source_revision = await session.scalar(
                    select(CreationRevisionRow).where(
                        CreationRevisionRow.id == request.source_revision_id,
                        CreationRevisionRow.owner_hash == owner_hash,
                        CreationRevisionRow.task_id.is_not(None),
                    )
                )
                if source_revision is None:
                    raise creation_error(
                        404, "not_found", "Source revision is unavailable."
                    )
                if not source_revision.confirmed:
                    raise creation_error(
                        409,
                        "invalid_state",
                        "Confirm the source revision before reusing it.",
                    )
                if (
                    content_digest(source_revision.text, source_revision.data)
                    != source_revision.sha256
                ):
                    raise creation_error(
                        409, "invalid_state", "Source revision integrity check failed."
                    )
                if request.text is not None and request.text != source_revision.text:
                    raise creation_error(
                        422,
                        "invalid_request",
                        "The material text must match its fixed source revision.",
                    )
                if request.data and request.data != source_revision.data:
                    raise creation_error(
                        422,
                        "invalid_request",
                        "The material data must match its fixed source revision.",
                    )
                if len(source_revision.text) > 30_000:
                    raise creation_error(
                        422,
                        "invalid_request",
                        "The source exceeds the material text limit.",
                    )
            now = utc_now()
            material_id, revision_id = uuid4(), uuid4()
            data = {**request.data, **(extra_data or {})}
            if source_revision is not None:
                data = dict(source_revision.data)
                data["source_revision_sha256"] = source_revision.sha256
            if file_bytes is not None and request.kind == "image":
                data.update(
                    {
                        "image_sha256": hashlib.sha256(file_bytes).hexdigest(),
                        "image_size_bytes": len(file_bytes),
                    }
                )
            if artifact is not None:
                data.update(
                    {
                        "duration_ms": artifact.duration_ms,
                        "size_bytes": artifact.size_bytes,
                        "media_sha256": artifact.sha256,
                    }
                )
            original_text = text_value if text_value is not None else request.text or ""
            if source_revision is not None:
                original_text = source_revision.text
            row = CreationMaterialRow(
                id=material_id,
                project_id=request.project_id,
                owner_hash=owner_hash,
                idempotency_key=key,
                request_sha256=digest,
                kind=request.kind,
                title=request.title,
                rights_statement=request.rights_statement,
                artifact_id=artifact.id if artifact is not None else None,
                document_id=request.document_id,
                source_url=request.source_url,
                source_revision_id=request.source_revision_id,
                binary_data=file_bytes,
                current_revision_id=revision_id,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush((row,))
            revision = CreationRevisionRow(
                id=revision_id,
                owner_hash=owner_hash,
                material_id=material_id,
                parent_revision_id=source_revision.id if source_revision else None,
                number=1,
                text=original_text,
                data=data,
                sha256=content_digest(original_text, data),
                confirmed=False,
                created_at=now,
            )
            session.add(revision)
            await session.flush()
            return await _material_view(session, row)

    async def list_materials(
        self, owner_hash: str, project_id: UUID | None = None, limit: int = 50
    ) -> tuple[CreationMaterialResponse, ...]:
        async with self._sessions() as session:
            query = select(CreationMaterialRow).where(
                CreationMaterialRow.owner_hash == owner_hash
            )
            if project_id is not None:
                query = query.where(CreationMaterialRow.project_id == project_id)
            rows = await session.scalars(
                query.order_by(CreationMaterialRow.created_at.desc()).limit(limit)
            )
            return tuple([await _material_view(session, row) for row in rows])

    async def get_material(
        self, material_id: UUID, owner_hash: str
    ) -> CreationMaterialResponse:
        async with self._sessions() as session:
            return await _material_view(
                session, await _owned_material(session, material_id, owner_hash)
            )

    async def get_image(self, material_id: UUID, owner_hash: str) -> tuple[bytes, str]:
        async with self._sessions() as session:
            row = await _owned_material(session, material_id, owner_hash)
            if row.kind != "image" or row.binary_data is None:
                raise creation_error(404, "not_found", "Image file is unavailable.")
            revision = await session.get(CreationRevisionRow, row.current_revision_id)
            if revision is None or hashlib.sha256(
                row.binary_data
            ).hexdigest() != revision.data.get("image_sha256"):
                raise creation_error(
                    503, "storage_unavailable", "Image integrity check failed."
                )
            return row.binary_data, str(
                revision.data.get("image_media_type", "application/octet-stream")
            )

    async def get_document_source(
        self, material_id: UUID, owner_hash: str
    ) -> tuple[bytes, str, str]:
        async with self._sessions() as session:
            row = await _owned_material(session, material_id, owner_hash)
            original = await session.scalar(
                select(CreationRevisionRow).where(
                    CreationRevisionRow.material_id == material_id,
                    CreationRevisionRow.number == 1,
                )
            )
            if (
                row.kind in {"image", "video"}
                or row.binary_data is None
                or original is None
            ):
                raise creation_error(
                    404, "not_found", "Document original is unavailable."
                )
            if hashlib.sha256(row.binary_data).hexdigest() != original.data.get(
                "file_sha256"
            ):
                raise creation_error(
                    503, "storage_unavailable", "Document integrity check failed."
                )
            media_type = str(
                original.data.get("file_media_type", "application/octet-stream")
            )
            filename = str(original.data.get("file_filename", "source.bin"))
            return row.binary_data, media_type, filename

    async def list_material_revisions(
        self, material_id: UUID, owner_hash: str
    ) -> tuple[CreationRevisionResponse, ...]:
        async with self._sessions() as session:
            await _owned_material(session, material_id, owner_hash)
            rows = await session.scalars(
                select(CreationRevisionRow)
                .where(CreationRevisionRow.material_id == material_id)
                .order_by(CreationRevisionRow.number.desc())
            )
            return tuple(_revision_view(row) for row in rows)

    async def save_material_revision(
        self,
        material_id: UUID,
        owner_hash: str,
        key: str,
        request: CreationRevisionSaveRequest,
    ) -> CreationMaterialResponse:
        async with self._sessions() as session, session.begin():
            await _lock_owner(session, owner_hash)
            row = await _owned_material(session, material_id, owner_hash, lock=True)
            replay = await _revision_replay(
                session, owner_hash, key, request, material_id=material_id
            )
            if replay is not None:
                return await _material_view(session, row, revision=replay)
            _expect_revision(row.current_revision_id, request.expected_revision_id)
            previous = await _require_revision(session, row.current_revision_id)
            data = dict(request.data)
            # Files and source identity never come from an editable JSON field.
            for protected in (
                "image_sha256",
                "image_size_bytes",
                "image_media_type",
                "duration_ms",
                "size_bytes",
                "media_sha256",
                "source_revision_sha256",
                "file_sha256",
                "file_size_bytes",
                "file_media_type",
                "file_filename",
                "extractor",
            ):
                if protected in previous.data:
                    data[protected] = previous.data[protected]
            revision = _new_revision(
                owner_hash, request.text, data, previous, key, request
            )
            revision.material_id = row.id
            session.add(revision)
            row.current_revision_id, row.updated_at = revision.id, utc_now()
            await _invalidate_downstream(
                session, owner_hash, material_revision_ids=[previous.id]
            )
            await session.flush()
            return await _material_view(session, row, revision=revision)

    async def confirm_material(
        self, material_id: UUID, owner_hash: str, request: CreationConfirmRequest
    ) -> CreationMaterialResponse:
        async with self._sessions() as session, session.begin():
            row = await _owned_material(session, material_id, owner_hash, lock=True)
            _expect_revision(row.current_revision_id, request.expected_revision_id)
            revision = await _require_revision(session, row.current_revision_id)
            revision.confirmed = True
            return await _material_view(session, row, revision=revision)

    async def replay_task(
        self, owner_hash: str, key: str, request: CreationTaskCreateRequest
    ) -> CreationTaskResponse | None:
        async with self._sessions() as session:
            existing = await session.scalar(
                select(CreationTaskRow).where(
                    CreationTaskRow.owner_hash == owner_hash,
                    CreationTaskRow.idempotency_key == key,
                )
            )
            if existing is None:
                return None
            _same_request(
                existing.request_sha256,
                _request_digest(request.model_dump(mode="json")),
            )
            return await _task_view(session, existing)

    async def create_task(
        self,
        owner_hash: str,
        key: str,
        request: CreationTaskCreateRequest,
        method_sha256: str,
    ) -> CreationTaskResponse:
        digest = _request_digest(request.model_dump(mode="json"))
        async with self._sessions() as session, session.begin():
            await _lock_owner(session, owner_hash)
            existing = await session.scalar(
                select(CreationTaskRow).where(
                    CreationTaskRow.owner_hash == owner_hash,
                    CreationTaskRow.idempotency_key == key,
                )
            )
            if existing is not None:
                _same_request(existing.request_sha256, digest)
                return await _task_view(session, existing)
            await _require_project(session, request.project_id, owner_hash)
            materials = await _task_materials(
                session, list(map(str, request.material_revision_ids)), owner_hash
            )
            now = utc_now()
            row = CreationTaskRow(
                id=uuid4(),
                project_id=request.project_id,
                owner_hash=owner_hash,
                idempotency_key=key,
                request_sha256=digest,
                skill_id=request.skill_id,
                method_sha256=method_sha256,
                material_revision_ids=list(map(str, request.material_revision_ids)),
                options=request.options,
                budget=request.budget.model_dump(),
                usage=CreationUsage().model_dump(),
                output_language=request.output_language,
                status="queued",
                attempt=1,
                stale=any(material.get("stale") for material in materials),
                limitations=[],
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush((row,))
            session.add(_requested_event(row))
            return await _task_view(session, row)

    async def list_tasks(
        self,
        owner_hash: str,
        project_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> tuple[CreationTaskResponse, ...]:
        async with self._sessions() as session:
            query = select(CreationTaskRow).where(
                CreationTaskRow.owner_hash == owner_hash
            )
            if project_id is not None:
                query = query.where(CreationTaskRow.project_id == project_id)
            if status is not None:
                query = query.where(CreationTaskRow.status == status)
            rows = await session.scalars(
                query.order_by(CreationTaskRow.created_at.desc()).limit(limit)
            )
            return tuple([await _task_view(session, row) for row in rows])

    async def get_task(
        self, task_id: UUID, owner_hash: str | None = None
    ) -> CreationTaskResponse:
        async with self._sessions() as session:
            return await _task_view(
                session, await _owned_task(session, task_id, owner_hash)
            )

    async def task_materials(
        self, task_id: UUID, owner_hash: str | None = None
    ) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            row = await _owned_task(session, task_id, owner_hash)
            return await _task_materials(
                session, row.material_revision_ids, row.owner_hash
            )

    async def material_revisions(
        self, revision_ids: list[str], owner_hash: str
    ) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            return await _task_materials(session, revision_ids, owner_hash)

    async def cancel_task(self, task_id: UUID, owner_hash: str) -> CreationTaskResponse:
        async with self._sessions() as session, session.begin():
            row = await _owned_task(session, task_id, owner_hash, lock=True)
            if row.status in {"queued", "processing"}:
                row.status, row.updated_at = "cancelled", utc_now()
                if row.usage.get("calls_reserved", 0):
                    row.usage = {
                        **row.usage,
                        "unknown_operations": max(
                            1, row.usage.get("unknown_operations", 0)
                        ),
                    }
            return await _task_view(session, row)

    async def list_task_revisions(
        self, task_id: UUID, owner_hash: str
    ) -> tuple[CreationRevisionResponse, ...]:
        async with self._sessions() as session:
            await _owned_task(session, task_id, owner_hash)
            rows = await session.scalars(
                select(CreationRevisionRow)
                .where(CreationRevisionRow.task_id == task_id)
                .order_by(CreationRevisionRow.number.desc())
            )
            return tuple(_revision_view(row) for row in rows)

    async def get_task_revision(
        self, task_id: UUID, revision_id: UUID, owner_hash: str
    ) -> CreationRevisionResponse:
        async with self._sessions() as session:
            await _owned_task(session, task_id, owner_hash)
            row = await session.scalar(
                select(CreationRevisionRow).where(
                    CreationRevisionRow.id == revision_id,
                    CreationRevisionRow.task_id == task_id,
                )
            )
            if row is None:
                raise creation_error(404, "not_found", "Revision is unavailable.")
            return _revision_view(row)

    async def save_task_revision(
        self,
        task_id: UUID,
        owner_hash: str,
        key: str,
        request: CreationRevisionSaveRequest,
    ) -> CreationTaskResponse:
        async with self._sessions() as session, session.begin():
            await _lock_owner(session, owner_hash)
            row = await _owned_task(session, task_id, owner_hash, lock=True)
            replay = await _revision_replay(
                session, owner_hash, key, request, task_id=task_id
            )
            if replay is not None:
                return await _task_view(session, row, revision=replay)
            _expect_revision(row.current_revision_id, request.expected_revision_id)
            if row.status in {"queued", "processing"}:
                raise creation_error(
                    409,
                    "invalid_state",
                    "Wait for the current candidate before editing.",
                )
            previous = await _require_revision(session, request.expected_revision_id)
            revision = _new_revision(
                owner_hash, request.text, request.data, previous, key, request
            )
            revision.task_id = task_id
            session.add(revision)
            row.current_revision_id, row.status, row.updated_at = (
                revision.id,
                "awaiting_confirmation",
                utc_now(),
            )
            await _invalidate_downstream(
                session, owner_hash, source_revision_ids=[previous.id]
            )
            await session.flush()
            return await _task_view(session, row, revision=revision)

    async def confirm_task(
        self, task_id: UUID, owner_hash: str, request: CreationConfirmRequest
    ) -> CreationTaskResponse:
        async with self._sessions() as session, session.begin():
            row = await _owned_task(session, task_id, owner_hash, lock=True)
            _expect_revision(row.current_revision_id, request.expected_revision_id)
            if row.status not in {"awaiting_confirmation", "completed"}:
                raise creation_error(
                    409, "invalid_state", "The candidate is not ready to confirm."
                )
            revision = await _require_revision(session, request.expected_revision_id)
            revision.confirmed = True
            row.status, row.updated_at = "completed", utc_now()
            return await _task_view(session, row, revision=revision)

    async def retry_task(
        self, task_id: UUID, owner_hash: str, key: str
    ) -> CreationTaskResponse:
        async with self._sessions() as session, session.begin():
            await _lock_owner(session, owner_hash)
            row = await _owned_task(session, task_id, owner_hash, lock=True)
            # An unknown accepted operation may still be billed. A user warning
            # is not enough to free or bypass its finite reservation.
            if row.usage.get("unknown_operations", 0) or row.usage.get(
                "calls_reserved", 0
            ):
                raise creation_error(
                    409,
                    "invalid_state",
                    "Resolve the unknown receipt and retained budget "
                    "before a new attempt.",
                )
            replay = await session.scalar(
                select(OutboxEventRow).where(
                    OutboxEventRow.aggregate_id == task_id,
                    OutboxEventRow.event_type == "creation.requested",
                    OutboxEventRow.payload["request_id"].astext
                    == hashlib.sha256(key.encode()).hexdigest(),
                )
            )
            if replay is not None:
                return await _task_view(session, row)
            if row.status not in {"failed", "cancelled"}:
                raise creation_error(
                    409,
                    "invalid_state",
                    "Only a failed or cancelled task can start a new attempt.",
                )
            if row.usage.get("calls_used", 0) >= row.budget["max_calls"]:
                raise creation_error(
                    409,
                    "analysis_budget_exceeded",
                    "The task call budget is exhausted.",
                )
            row.attempt += 1
            row.status, row.error_code, row.worker_id, row.deadline_at = (
                "queued",
                None,
                None,
                None,
            )
            row.updated_at = utc_now()
            session.add(_requested_event(row, key))
            return await _task_view(session, row)

    async def claim_task(
        self, task_id: UUID, worker_id: str, *, expected_attempt: int | None = None
    ) -> dict[str, Any] | None:
        async with self._sessions() as session, session.begin():
            row = await _owned_task(session, task_id, None, lock=True)
            if expected_attempt is not None and row.attempt != expected_attempt:
                return None
            if row.status == "processing":
                if row.usage.get("calls_reserved", 0) or row.usage.get(
                    "unknown_operations", 0
                ):
                    row.status, row.error_code = (
                        "outcome_unknown",
                        "analysis_outcome_unknown",
                    )
                    row.usage = {
                        **row.usage,
                        "unknown_operations": max(
                            1, row.usage.get("unknown_operations", 0)
                        ),
                    }
                return None
            if row.status != "queued":
                return None
            row.status, row.worker_id, row.updated_at = (
                "processing",
                worker_id,
                utc_now(),
            )
            row.deadline_at = utc_now() + timedelta(
                seconds=row.budget["timeout_seconds"]
            )
            materials = await _task_materials(
                session, row.material_revision_ids, row.owner_hash
            )
            return {
                "task": await _task_view(session, row),
                "materials": materials,
                "method_sha256": row.method_sha256,
            }

    async def finish_task(
        self,
        task_id: UUID,
        worker_id: str,
        text_value: str,
        data: dict[str, Any],
        limitations: list[str] | None = None,
    ) -> CreationTaskResponse:
        async with self._sessions() as session, session.begin():
            row = await _owned_task(session, task_id, None, lock=True)
            if row.status != "processing" or row.worker_id != worker_id:
                return await _task_view(session, row)
            if len(text_value) > 100_000 or "\x00" in text_value:
                raise ValueError("candidate text exceeds the editable result bound")
            if (
                len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode())
                > 1024 * 1024
            ):
                raise ValueError("candidate data exceeds the editable result bound")
            previous = (
                await session.get(CreationRevisionRow, row.current_revision_id)
                if row.current_revision_id
                else None
            )
            revision = CreationRevisionRow(
                id=uuid4(),
                owner_hash=row.owner_hash,
                task_id=task_id,
                number=1 if previous is None else previous.number + 1,
                parent_revision_id=previous.id if previous else None,
                text=text_value,
                data=data,
                sha256=content_digest(text_value, data),
                confirmed=False,
                created_at=utc_now(),
            )
            session.add(revision)
            row.current_revision_id, row.status, row.updated_at = (
                revision.id,
                "awaiting_confirmation",
                utc_now(),
            )
            row.limitations = limitations or []
            if previous is not None:
                await _invalidate_downstream(
                    session, row.owner_hash, source_revision_ids=[previous.id]
                )
            await session.flush()
            return await _task_view(session, row, revision=revision)

    async def fail_task(
        self,
        task_id: UUID,
        worker_id: str,
        error_code: str,
        *,
        outcome_unknown: bool = False,
    ) -> CreationTaskResponse:
        async with self._sessions() as session, session.begin():
            row = await _owned_task(session, task_id, None, lock=True)
            # A slot-waiting Activity has not claimed or reserved anything yet.
            # Its exact current Workflow can fail it after worker loss; other
            # attempts and ordinary failures still require the claimed worker.
            lost_before_claim = (
                row.status == "queued"
                and row.worker_id is None
                and worker_id == f"creation/{row.id}/{row.attempt}"
                and error_code == "analysis_worker_lost"
                and not outcome_unknown
                and not row.usage.get("calls_reserved", 0)
                and not row.usage.get("unknown_operations", 0)
            )
            if not lost_before_claim and (
                row.worker_id != worker_id
                or row.status not in {"processing", "cancelled"}
            ):
                return await _task_view(session, row)
            unknown = outcome_unknown or bool(row.usage.get("calls_reserved", 0))
            if row.status != "cancelled":
                row.status = "outcome_unknown" if unknown else "failed"
            if unknown:
                row.usage = {
                    **row.usage,
                    "unknown_operations": max(
                        1, row.usage.get("unknown_operations", 0)
                    ),
                }
            row.error_code, row.updated_at = error_code[:64], utc_now()
            return await _task_view(session, row)

    async def mark_call_sent(self, task_id: UUID, worker_id: str) -> None:
        async with self._sessions() as session, session.begin():
            row = await _owned_task(session, task_id, None, lock=True)
            _require_worker(row, worker_id)
            usage = CreationUsage.model_validate(row.usage)
            if usage.calls_reserved or usage.unknown_operations:
                raise creation_error(
                    409,
                    "invalid_state",
                    "A previous model operation has an unknown receipt.",
                )
            if (
                usage.calls_used + usage.calls_reserved >= row.budget["max_calls"]
                or row.deadline_at is None
                or as_utc(utc_now()) >= as_utc(row.deadline_at)
            ):
                raise creation_error(
                    409,
                    "analysis_budget_exceeded",
                    "The task budget or deadline is exhausted.",
                )
            # Existing adapters return no audited monetary usage. Never claim
            # a hard money limit can be enforced without that contract.
            if row.budget.get("max_cost_minor") is not None:
                raise creation_error(
                    409,
                    "invalid_state",
                    "The provider cannot verify a monetary spending limit.",
                )
            row.usage = {
                **row.usage,
                "calls_reserved": usage.calls_reserved + 1,
                "tokens_reserved": row.budget["max_tokens"],
            }

    async def settle_call(
        self, task_id: UUID, worker_id: str, *, known: bool, executed: bool = True
    ) -> None:
        async with self._sessions() as session, session.begin():
            row = await _owned_task(session, task_id, None, lock=True)
            if row.worker_id != worker_id:
                return
            usage = CreationUsage.model_validate(row.usage)
            if known:
                row.usage = {
                    **row.usage,
                    "calls_used": usage.calls_used
                    + (usage.calls_reserved if executed else 0),
                    "calls_reserved": 0,
                    "tokens_reserved": 0,
                }
            else:
                row.usage = {
                    **row.usage,
                    "unknown_operations": max(1, usage.unknown_operations),
                }

    async def runtime_availability(
        self, *, stale_seconds: int = 30
    ) -> tuple[bool, bool]:
        async with self._sessions() as session:
            provider = await session.scalar(
                select(AiProviderProfileRow.key)
                .where(AiProviderProfileRow.is_active.is_(True))
                .limit(1)
            )
            worker = await session.scalar(
                select(AnalysisWorkerHeartbeatRow.worker_id)
                .where(
                    AnalysisWorkerHeartbeatRow.message_schema_version
                    == ANALYSIS_MESSAGE_SCHEMA_VERSION,
                    AnalysisWorkerHeartbeatRow.last_seen_at
                    >= utc_now() - timedelta(seconds=stale_seconds),
                )
                .limit(1)
            )
            return provider is not None, worker is not None

    async def get_export(
        self, task_id: UUID, revision_id: UUID, format: str, owner_hash: str
    ) -> ExportArtifact | None:
        async with self._sessions() as session:
            await _owned_task(session, task_id, owner_hash)
            row = await session.scalar(
                select(CreationExportRow).where(
                    CreationExportRow.task_id == task_id,
                    CreationExportRow.revision_id == revision_id,
                    CreationExportRow.format == format,
                )
            )
            return None if row is None else _export_view(row)

    async def save_export(
        self,
        task_id: UUID,
        revision_id: UUID,
        format: str,
        owner_hash: str,
        artifact: ExportArtifact,
    ) -> ExportArtifact:
        if not 0 < len(artifact.data) <= 64 * 1024**2:
            raise creation_error(
                422, "invalid_request", "Export exceeds its byte limit."
            )
        async with self._sessions() as session, session.begin():
            await _lock_owner(session, owner_hash)
            await _owned_task(session, task_id, owner_hash)
            revision = await session.scalar(
                select(CreationRevisionRow).where(
                    CreationRevisionRow.id == revision_id,
                    CreationRevisionRow.task_id == task_id,
                    CreationRevisionRow.confirmed.is_(True),
                )
            )
            if revision is None:
                raise creation_error(
                    409, "invalid_state", "Confirm this revision before exporting."
                )
            existing = await session.scalar(
                select(CreationExportRow).where(
                    CreationExportRow.revision_id == revision_id,
                    CreationExportRow.format == format,
                )
            )
            if existing is not None:
                return _export_view(existing)
            row = CreationExportRow(
                id=uuid4(),
                task_id=task_id,
                revision_id=revision_id,
                format=format,
                filename=artifact.filename,
                media_type=artifact.media_type,
                sha256=hashlib.sha256(artifact.data).hexdigest(),
                binary_data=artifact.data,
                export_metadata=dict(artifact.metadata),
                created_at=utc_now(),
            )
            session.add(row)
            await session.flush()
            return _export_view(row)

    async def _require_artifact(
        self,
        session: AsyncSession,
        request: CreationMaterialCreateRequest,
        owner_hash: str,
    ) -> ArtifactRow | None:
        if request.artifact_id is None and request.download_id is None:
            return None
        query = (
            select(ArtifactRow)
            .join(DownloadJobRow, ArtifactRow.job_id == DownloadJobRow.id)
            .where(
                DownloadJobRow.owner_hash == owner_hash,
                DownloadJobRow.status == "succeeded",
                ArtifactRow.deleted_at.is_(None),
            )
        )
        query = (
            query.where(ArtifactRow.id == request.artifact_id)
            if request.artifact_id
            else query.where(ArtifactRow.job_id == request.download_id)
        )
        artifact = await session.scalar(query.with_for_update())
        if artifact is None:
            raise creation_error(404, "not_found", "The owned video is not ready.")
        if artifact.duration_ms > 30 * 60 * 1_000 or artifact.size_bytes > 2 * 1024**3:
            raise creation_error(
                422, "invalid_request", "Video exceeds the supported material limits."
            )
        return artifact

    async def _require_document(
        self, session: AsyncSession, document_id: UUID, owner_hash: str
    ) -> DocumentRow:
        row = await session.scalar(
            select(DocumentRow)
            .where(
                DocumentRow.id == document_id,
                DocumentRow.owner_hash == owner_hash,
                DocumentRow.status == "ready",
                DocumentRow.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if row is None:
            raise creation_error(404, "not_found", "The owned document is not ready.")
        return row


async def _lock_owner(session: AsyncSession, owner_hash: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:owner))"), {"owner": owner_hash}
    )


async def _require_project(
    session: AsyncSession, project_id: UUID | None, owner_hash: str
) -> None:
    if (
        project_id is not None
        and await session.scalar(
            select(CreationProjectRow.id).where(
                CreationProjectRow.id == project_id,
                CreationProjectRow.owner_hash == owner_hash,
            )
        )
        is None
    ):
        raise creation_error(404, "not_found", "Project is unavailable.")


async def _owned_material(
    session: AsyncSession, material_id: UUID, owner_hash: str, *, lock: bool = False
) -> CreationMaterialRow:
    query = select(CreationMaterialRow).where(
        CreationMaterialRow.id == material_id,
        CreationMaterialRow.owner_hash == owner_hash,
    )
    row = await session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise creation_error(404, "not_found", "Material is unavailable.")
    return row


async def _owned_task(
    session: AsyncSession, task_id: UUID, owner_hash: str | None, *, lock: bool = False
) -> CreationTaskRow:
    query = select(CreationTaskRow).where(CreationTaskRow.id == task_id)
    if owner_hash is not None:
        query = query.where(CreationTaskRow.owner_hash == owner_hash)
    row = await session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise creation_error(404, "not_found", "Task is unavailable.")
    return row


async def _require_revision(
    session: AsyncSession, revision_id: UUID
) -> CreationRevisionRow:
    revision = await session.get(CreationRevisionRow, revision_id)
    if revision is None:
        raise creation_error(409, "invalid_state", "The saved revision is unavailable.")
    return revision


async def _material_view(
    session: AsyncSession,
    row: CreationMaterialRow,
    *,
    revision: CreationRevisionRow | None = None,
) -> CreationMaterialResponse:
    actual = revision or await _require_revision(session, row.current_revision_id)
    return CreationMaterialResponse(
        id=row.id,
        project_id=row.project_id,
        source_revision_id=row.source_revision_id,
        kind=cast(Any, row.kind),
        title=row.title,
        rights_statement=row.rights_statement,
        artifact_id=row.artifact_id,
        document_id=row.document_id,
        source_url=row.source_url,
        current_revision=_revision_view(actual),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _task_view(
    session: AsyncSession,
    row: CreationTaskRow,
    *,
    revision: CreationRevisionRow | None = None,
) -> CreationTaskResponse:
    actual = revision or (
        await _require_revision(session, row.current_revision_id)
        if row.current_revision_id
        else None
    )
    return CreationTaskResponse(
        id=row.id,
        project_id=row.project_id,
        skill_id=row.skill_id,
        status=cast(Any, row.status),
        material_revision_ids=tuple(UUID(value) for value in row.material_revision_ids),
        options=row.options,
        budget=cast(Any, row.budget),
        usage=cast(Any, row.usage),
        output_language=row.output_language,
        attempt=row.attempt,
        revision=_revision_view(actual) if actual else None,
        stale=row.stale,
        limitations=tuple(row.limitations),
        error_code=row.error_code,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _revision_view(row: CreationRevisionRow) -> CreationRevisionResponse:
    return CreationRevisionResponse(
        id=row.id,
        number=row.number,
        parent_revision_id=row.parent_revision_id,
        text=row.text,
        data=row.data,
        sha256=row.sha256,
        confirmed=row.confirmed,
        created_at=row.created_at,
    )


def _new_revision(
    owner_hash: str,
    text_value: str,
    data: dict[str, Any],
    previous: CreationRevisionRow,
    key: str,
    request: CreationRevisionSaveRequest,
) -> CreationRevisionRow:
    return CreationRevisionRow(
        id=uuid4(),
        owner_hash=owner_hash,
        parent_revision_id=previous.id,
        idempotency_key=key,
        request_sha256=_request_digest(request.model_dump(mode="json")),
        number=previous.number + 1,
        text=text_value,
        data=data,
        sha256=content_digest(text_value, data),
        confirmed=False,
        created_at=utc_now(),
    )


async def _revision_replay(
    session: AsyncSession,
    owner_hash: str,
    key: str,
    request: CreationRevisionSaveRequest,
    *,
    material_id: UUID | None = None,
    task_id: UUID | None = None,
) -> CreationRevisionRow | None:
    row = await session.scalar(
        select(CreationRevisionRow).where(
            CreationRevisionRow.owner_hash == owner_hash,
            CreationRevisionRow.idempotency_key == key,
        )
    )
    if row is not None:
        _same_request(
            row.request_sha256 or "", _request_digest(request.model_dump(mode="json"))
        )
        if row.material_id != material_id or row.task_id != task_id:
            raise creation_error(
                409,
                "idempotency_conflict",
                "The save key belongs to a different resource.",
            )
    return row


def _request_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _same_request(previous: str, incoming: str) -> None:
    if previous != incoming:
        raise creation_error(
            409,
            "idempotency_conflict",
            "The idempotency key was used for different content.",
        )


def _expect_revision(current: UUID | None, expected: UUID) -> None:
    if current != expected:
        raise creation_error(
            409,
            "job_conflict",
            "The current revision changed; reload and compare your changes.",
        )


def _requested_event(row: CreationTaskRow, key: str | None = None) -> OutboxEventRow:
    return OutboxEventRow(
        id=uuid4(),
        aggregate_type="creation_task",
        aggregate_id=row.id,
        aggregate_version=row.attempt,
        event_type="creation.requested",
        payload={
            "task_id": str(row.id),
            "attempt": row.attempt,
            "request_id": hashlib.sha256(
                (key or row.idempotency_key).encode()
            ).hexdigest(),
        },
        available_at=utc_now(),
        created_at=utc_now(),
    )


def _require_worker(row: CreationTaskRow, worker_id: str) -> None:
    if row.status != "processing" or row.worker_id != worker_id:
        raise creation_error(409, "invalid_state", "Task execution ownership changed.")


def _export_view(row: CreationExportRow) -> ExportArtifact:
    if hashlib.sha256(row.binary_data).hexdigest() != row.sha256:
        raise creation_error(
            503, "storage_unavailable", "Export integrity check failed."
        )
    return ExportArtifact(
        row.filename, row.media_type, row.binary_data, row.export_metadata
    )


async def _invalidate_downstream(
    session: AsyncSession,
    owner_hash: str,
    *,
    material_revision_ids: list[UUID] | None = None,
    source_revision_ids: list[UUID] | None = None,
) -> None:
    """Keep frozen descendants, but invalidate every dependent result transitively."""
    material_ids = list(material_revision_ids or [])
    sources = list(source_revision_ids or [])
    visited: set[UUID] = set()
    while material_ids or sources:
        if sources:
            derived = await session.scalars(
                select(CreationRevisionRow.id)
                .join(
                    CreationMaterialRow,
                    CreationRevisionRow.material_id == CreationMaterialRow.id,
                )
                .where(
                    CreationMaterialRow.owner_hash == owner_hash,
                    CreationMaterialRow.source_revision_id.in_(sources),
                )
            )
            material_ids.extend(derived)
        if not material_ids:
            return
        descendants = list(
            await session.scalars(
                select(CreationTaskRow).where(
                    CreationTaskRow.owner_hash == owner_hash,
                    or_(
                        *(
                            CreationTaskRow.material_revision_ids.contains([str(value)])
                            for value in material_ids
                        )
                    ),
                )
            )
        )
        sources, material_ids = [], []
        for descendant in descendants:
            if descendant.id in visited:
                continue
            visited.add(descendant.id)
            descendant.stale = True
            descendant.updated_at = utc_now()
            if descendant.current_revision_id is not None:
                sources.append(descendant.current_revision_id)


async def _task_materials(
    session: AsyncSession, revision_ids: list[str], owner_hash: str
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for revision_id in revision_ids:
        pair = (
            await session.execute(
                select(CreationRevisionRow, CreationMaterialRow)
                .join(
                    CreationMaterialRow,
                    CreationRevisionRow.material_id == CreationMaterialRow.id,
                )
                .where(
                    CreationRevisionRow.id == UUID(revision_id),
                    CreationMaterialRow.owner_hash == owner_hash,
                )
            )
        ).one_or_none()
        if pair is None or not pair[0].confirmed:
            raise creation_error(
                409, "invalid_state", "Every task material must be owned and confirmed."
            )
        revision, material = pair
        if content_digest(revision.text, revision.data) != revision.sha256:
            raise creation_error(
                409, "invalid_state", "Material integrity check failed."
            )
        value: dict[str, Any] = {
            "id": str(material.id),
            "revision_id": str(revision.id),
            "kind": {"text": "article", "screenplay": "script"}.get(
                material.kind, material.kind
            ),
            "title": material.title,
            "text": revision.text,
            "sha256": revision.sha256,
            "rights_statement": material.rights_statement,
            "confirmed": revision.confirmed,
            "data": revision.data,
            "source_url": material.source_url,
            "artifact_id": str(material.artifact_id) if material.artifact_id else None,
            "document_id": str(material.document_id) if material.document_id else None,
            "source_revision_id": str(material.source_revision_id)
            if material.source_revision_id
            else None,
            "stale": material.current_revision_id != revision.id,
        }
        if material.source_revision_id is not None:
            source_revision = await _require_revision(
                session, material.source_revision_id
            )
            source_task = await session.get(CreationTaskRow, source_revision.task_id)
            if source_task is None or source_task.owner_hash != owner_hash:
                raise creation_error(
                    409, "invalid_state", "Source task is unavailable."
                )
            value["stale"] = bool(
                value["stale"]
                or source_task.stale
                or source_task.current_revision_id != source_revision.id
            )
        if material.binary_data is not None and material.kind == "image":
            if hashlib.sha256(material.binary_data).hexdigest() != revision.data.get(
                "image_sha256"
            ):
                raise creation_error(
                    409, "invalid_state", "Image integrity check failed."
                )
            value["image_data_base64"] = base64.b64encode(material.binary_data).decode()
        if material.artifact_id is not None:
            artifact = await session.scalar(
                select(ArtifactRow)
                .join(DownloadJobRow, DownloadJobRow.id == ArtifactRow.job_id)
                .where(
                    ArtifactRow.id == material.artifact_id,
                    ArtifactRow.deleted_at.is_(None),
                    DownloadJobRow.owner_hash == owner_hash,
                    DownloadJobRow.status == "succeeded",
                )
            )
            if artifact is None:
                raise creation_error(
                    409, "invalid_state", "Video original is unavailable."
                )
            value["source"] = {
                "bucket": artifact.bucket,
                "object_key": artifact.object_key,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
                "duration_ms": artifact.duration_ms,
                "content_type": artifact.content_type,
                "media_metadata": artifact.media_metadata,
            }
        if material.document_id is not None:
            artifact = await session.scalar(
                select(DocumentArtifactRow)
                .join(DocumentRow, DocumentRow.id == DocumentArtifactRow.document_id)
                .where(
                    DocumentArtifactRow.document_id == material.document_id,
                    DocumentArtifactRow.kind == "normalized",
                    DocumentArtifactRow.status == "ready",
                    DocumentRow.owner_hash == owner_hash,
                    DocumentRow.status == "ready",
                    DocumentRow.deleted_at.is_(None),
                )
            )
            if artifact is None:
                raise creation_error(
                    409, "invalid_state", "Document original is unavailable."
                )
            value["document_source"] = {
                "bucket": artifact.bucket,
                "object_key": artifact.object_key,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
                "content_type": artifact.content_type,
            }
        values.append(value)
    if sum(len(str(value["text"])) for value in values) > 30_000:
        raise creation_error(
            422, "invalid_request", "Combined material text exceeds 30,000 characters."
        )
    if sum(value["kind"] == "image" for value in values) > 20:
        raise creation_error(
            422, "invalid_request", "The task supports at most 20 image files."
        )
    return values
