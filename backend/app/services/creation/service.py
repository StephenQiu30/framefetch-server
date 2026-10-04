"""Creation admission and human decisions; no API background model execution."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
from io import BytesIO
from pathlib import PurePath
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from app.services.creation.catalog import list_creation_skills
from app.services.creation.errors import creation_error
from app.services.creation.models import (
    CreationConfirmRequest,
    CreationMaterialCreateRequest,
    CreationMaterialResponse,
    CreationProjectCreateRequest,
    CreationProjectResponse,
    CreationRevisionResponse,
    CreationRevisionSaveRequest,
    CreationSkillResponse,
    CreationTaskCreateRequest,
    CreationTaskResponse,
)
from app.services.creation.ports import CreationPersistence
from app.services.creation.sources import extract_document
from PIL import Image, UnidentifiedImageError


class CreationService:
    def __init__(
        self,
        repository: CreationPersistence,
        *,
        enabled: bool = True,
        worker_stale_seconds: int = 30,
    ) -> None:
        self.repository = repository
        self._enabled = enabled
        self._worker_stale_seconds = worker_stale_seconds

    async def list_skills(self) -> tuple[CreationSkillResponse, ...]:
        provider, worker = await self.repository.runtime_availability(
            stale_seconds=self._worker_stale_seconds
        )
        result = []
        for skill in list_creation_skills():
            limitations = list(skill.limitations)
            available = (
                self._enabled
                and worker
                and (provider or skill.execution_kind != "model")
            )
            if not self._enabled:
                limitations.append("本部署未启用内容处理。")
            if not worker:
                limitations.append(
                    "宿主处理 Worker 未就绪，材料编辑与已保存版本仍可使用。"
                )
            if skill.execution_kind == "model":
                if not provider:
                    limitations.append("尚未配置活跃模型线路。")
                else:
                    limitations.append(
                        "仅开放受控内测；模型候选需人工核查，正式专业质量评测未完成。"
                    )
            if skill.id == "subtitle-edit":
                limitations.append("校订用户提供的字幕；当前任务不执行自动语音转录。")
            if skill.id == "shot-study":
                limitations.append(
                    "镜头检测与帧证据需已导入视频及宿主 FFmpeg；"
                    "非对白声音只接受人工笔记。"
                )
            result.append(
                skill.model_copy(
                    update={"available": available, "limitations": tuple(limitations)}
                )
            )
        return tuple(result)

    async def create_project(
        self, owner_hash: str, key: str, request: CreationProjectCreateRequest
    ) -> CreationProjectResponse:
        _validate_identity(owner_hash, key)
        if not request.title.strip():
            raise creation_error(
                422, "invalid_request", "Project title must contain text."
            )
        return await self.repository.create_project(owner_hash, key, request)

    async def list_projects(
        self, owner_hash: str, limit: int = 50
    ) -> tuple[CreationProjectResponse, ...]:
        return await self.repository.list_projects(owner_hash, limit)

    async def create_material(
        self, owner_hash: str, key: str, request: CreationMaterialCreateRequest
    ) -> CreationMaterialResponse:
        _validate_identity(owner_hash, key)
        if not request.title.strip() or not request.rights_statement.strip():
            raise creation_error(
                422, "invalid_request", "Title and rights statement must contain text."
            )
        _bounded_data(request.data)
        if request.text is not None:
            _validate_text(request.text, maximum=30_000)
        if request.source_url is not None:
            _reference_url(request.source_url)
        if request.document_id is not None:
            raise creation_error(
                422,
                "invalid_request",
                "Upload the actual document file; free text cannot establish "
                "the original content of an existing document.",
            )
        file_bytes, metadata = (
            _decode_image(request.image_data_base64)
            if request.kind == "image"
            else (None, {})
        )
        text_value = None
        if request.document_data_base64 is not None:
            file_bytes, metadata = _decode_document(request)
            try:
                text_value = await asyncio.to_thread(
                    extract_document,
                    str(request.document_filename),
                    file_bytes,
                    kind="script" if request.kind == "screenplay" else request.kind,
                )
            except Exception as error:
                raise creation_error(
                    422,
                    "invalid_request",
                    "Provide readable UTF-8, DOCX or text PDF within 10 MiB "
                    "and 30000 characters.",
                ) from error
            if request.text is not None and request.text != text_value:
                raise creation_error(
                    422,
                    "invalid_request",
                    "Text must match the actual document extraction.",
                )
            _validate_text(text_value, maximum=30_000)
        return await self.repository.create_material(
            owner_hash,
            key,
            request,
            file_bytes=file_bytes,
            text_value=text_value,
            extra_data=metadata,
        )

    async def list_materials(
        self, owner_hash: str, project_id: UUID | None = None, limit: int = 50
    ) -> tuple[CreationMaterialResponse, ...]:
        return await self.repository.list_materials(owner_hash, project_id, limit)

    async def get_material(
        self, material_id: UUID, owner_hash: str
    ) -> CreationMaterialResponse:
        return await self.repository.get_material(material_id, owner_hash)

    async def list_material_revisions(
        self, material_id: UUID, owner_hash: str
    ) -> tuple[CreationRevisionResponse, ...]:
        return await self.repository.list_material_revisions(material_id, owner_hash)

    async def save_material_revision(
        self,
        material_id: UUID,
        owner_hash: str,
        key: str,
        request: CreationRevisionSaveRequest,
    ) -> CreationMaterialResponse:
        _validate_identity(owner_hash, key)
        _validate_text(request.text, maximum=30_000, empty_allowed=True)
        _bounded_data(request.data)
        material = await self.repository.get_material(material_id, owner_hash)
        if (
            material.kind not in {"image", "video"}
            and not request.text.strip()
            and material.source_url is None
        ):
            raise creation_error(
                422,
                "invalid_request",
                "The material revision must contain readable text.",
            )
        return await self.repository.save_material_revision(
            material_id, owner_hash, key, request
        )

    async def confirm_material(
        self, material_id: UUID, owner_hash: str, request: CreationConfirmRequest
    ) -> CreationMaterialResponse:
        return await self.repository.confirm_material(material_id, owner_hash, request)

    async def create_task(
        self, owner_hash: str, key: str, request: CreationTaskCreateRequest
    ) -> CreationTaskResponse:
        _validate_identity(owner_hash, key)
        _bounded_data(request.options)
        replay = await self.repository.replay_task(owner_hash, key, request)
        if replay is not None:
            return replay
        skill = next(
            (item for item in await self.list_skills() if item.id == request.skill_id),
            None,
        )
        if skill is None:
            raise creation_error(
                422,
                "invalid_request",
                "This content capability is outside the active product scope.",
            )
        # Validate exact owner-scoped revisions before enqueueing or calling a
        # provider. The repository repeats this check in its create transaction.
        materials = await self.repository.material_revisions(
            list(map(str, request.material_revision_ids)), owner_hash
        )
        _validate_capability_materials(request.skill_id, materials, request.options)
        if not skill.available:
            raise creation_error(
                503,
                "service_unavailable",
                "The required processing capability is not ready.",
            )
        if (
            request.budget.max_cost_minor is not None
            and skill.execution_kind == "model"
        ):
            raise creation_error(
                422,
                "invalid_request",
                "This provider cannot enforce an audited monetary limit.",
            )
        if (
            request.skill_id == "article-edit"
            and request.options.get("mode", "format") != "format"
        ):
            provider, _ = await self.repository.runtime_availability(
                stale_seconds=self._worker_stale_seconds
            )
            if not provider:
                raise creation_error(
                    503,
                    "service_unavailable",
                    "A rewrite requires an active model; "
                    "format mode remains available.",
                )
        return await self.repository.create_task(
            owner_hash, key, request, skill.method_sha256
        )

    async def list_tasks(
        self,
        owner_hash: str,
        project_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> tuple[CreationTaskResponse, ...]:
        return await self.repository.list_tasks(owner_hash, project_id, status, limit)

    async def get_task(self, task_id: UUID, owner_hash: str) -> CreationTaskResponse:
        return await self.repository.get_task(task_id, owner_hash)

    async def cancel_task(self, task_id: UUID, owner_hash: str) -> CreationTaskResponse:
        return await self.repository.cancel_task(task_id, owner_hash)

    async def list_task_revisions(
        self, task_id: UUID, owner_hash: str
    ) -> tuple[CreationRevisionResponse, ...]:
        return await self.repository.list_task_revisions(task_id, owner_hash)

    async def save_task_revision(
        self,
        task_id: UUID,
        owner_hash: str,
        key: str,
        request: CreationRevisionSaveRequest,
    ) -> CreationTaskResponse:
        _validate_identity(owner_hash, key)
        _validate_text(request.text, maximum=100_000)
        _bounded_data(request.data)
        return await self.repository.save_task_revision(
            task_id, owner_hash, key, request
        )

    async def confirm_task(
        self, task_id: UUID, owner_hash: str, request: CreationConfirmRequest
    ) -> CreationTaskResponse:
        return await self.repository.confirm_task(task_id, owner_hash, request)

    async def retry_task(
        self, task_id: UUID, owner_hash: str, key: str
    ) -> CreationTaskResponse:
        _validate_identity(owner_hash, key)
        return await self.repository.retry_task(task_id, owner_hash, key)


def _validate_identity(owner_hash: str, key: str) -> None:
    if (
        len(owner_hash) != 64
        or any(value not in "0123456789abcdef" for value in owner_hash)
        or not 1 <= len(key) <= 128
        or any(ord(value) < 32 for value in key)
    ):
        raise creation_error(
            422, "invalid_request", "Invalid owner identity or idempotency key."
        )


def _validate_text(value: str, *, maximum: int, empty_allowed: bool = False) -> None:
    if (
        len(value) > maximum
        or (not empty_allowed and not value.strip())
        or any(ord(char) < 32 and char not in "\r\n\t" for char in value)
    ):
        raise creation_error(
            422, "invalid_request", "Provide readable, bounded UTF-8 text."
        )


def _decode_document(
    request: CreationMaterialCreateRequest,
) -> tuple[bytes, dict[str, Any]]:
    filename = str(request.document_filename)
    if (
        PurePath(filename).name != filename
        or "\\" in filename
        or any(ord(char) < 32 for char in filename)
    ):
        raise creation_error(
            422, "invalid_request", "Provide a document filename without directories."
        )
    try:
        raw = base64.b64decode(str(request.document_data_base64), validate=True)
    except (ValueError, binascii.Error) as error:
        raise creation_error(
            422, "invalid_request", "Invalid document data."
        ) from error
    if not 0 < len(raw) <= 10 * 1024 * 1024:
        raise creation_error(
            422, "invalid_request", "Document exceeds the 10 MiB bound."
        )
    suffix = PurePath(filename).suffix.casefold()
    return raw, {
        "file_filename": filename,
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "file_size_bytes": len(raw),
        "extractor": "creation-local-document-2026-10-04",
        "file_media_type": {
            ".docx": "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document",
            ".pdf": "application/pdf",
        }.get(suffix, "text/plain; charset=utf-8"),
    }


def _bounded_data(data: dict[str, Any]) -> None:
    try:
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise creation_error(
            422, "invalid_request", "Structured content must be valid finite JSON."
        ) from error
    if len(payload) > 1_000_000:
        raise creation_error(
            422, "invalid_request", "Structured content exceeds its finite size limit."
        )


def _reference_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as error:
        raise creation_error(422, "invalid_url", "Reference URL is invalid.") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise creation_error(
            422, "invalid_url", "Reference requires an HTTP(S) URL without credentials."
        )
    # Actual network execution separately resolves DNS and checks every redirect.
    if parsed.hostname.casefold() in {"localhost", "localhost.localdomain"}:
        raise creation_error(
            422, "invalid_url", "Private reference destinations are forbidden."
        )


def _decode_image(value: str | None) -> tuple[bytes, dict[str, Any]]:
    try:
        if value is None:
            raise ValueError("missing image")
        raw = base64.b64decode(value, validate=True)
        if not 0 < len(raw) <= 10 * 1024**2:
            raise ValueError("image bytes exceed budget")
        with Image.open(BytesIO(raw)) as image:
            kind = image.format
            if (
                kind not in {"PNG", "JPEG", "WEBP"}
                or image.width * image.height > 25_000_000
                or image.width > 10_000
                or image.height > 10_000
                or getattr(image, "n_frames", 1) != 1
            ):
                raise ValueError("image format or dimensions exceed budget")
            metadata = {
                "image_media_type": {
                    "PNG": "image/png",
                    "JPEG": "image/jpeg",
                    "WEBP": "image/webp",
                }[kind],
                "width": image.width,
                "height": image.height,
            }
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            image.load()
        return raw, metadata
    except (
        binascii.Error,
        ValueError,
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as error:
        raise creation_error(
            422, "invalid_request", "Provide a valid bounded PNG, JPEG or WebP image."
        ) from error


def _validate_capability_materials(
    skill_id: str, materials: list[dict[str, Any]], options: dict[str, Any]
) -> None:
    kinds = {item["kind"] for item in materials}
    if any(
        item["kind"] in {"article", "script", "subtitle", "reference"}
        and not str(item.get("text", "")).strip()
        for item in materials
    ):
        raise creation_error(
            422,
            "invalid_request",
            "Provide and confirm readable source text; "
            "a URL alone is not source evidence.",
        )
    required: dict[str, set[str]] = {
        "script-diagnosis": {"script"},
        "shot-study": {"video"},
        "subtitle-edit": {"video", "subtitle"},
        "script-cut-compare": {"script", "video"},
        "continuity-review": {"video"},
        "article-edit": {"article"},
        "wechat-package": {"article"},
        "xhs-cards": {"article"},
        "source-extract": {"reference"},
    }
    if not required.get(skill_id, set()) <= kinds:
        raise creation_error(
            422,
            "invalid_request",
            "The selected task is missing its required confirmed material kinds.",
        )
    if skill_id in {"article-write", "film-research"} and not kinds & {
        "article",
        "script",
        "reference",
    }:
        raise creation_error(
            422,
            "invalid_request",
            "Provide author viewpoints or authorized text references.",
        )
    if skill_id == "visual-assets" and not kinds & {"article", "image"}:
        raise creation_error(
            422, "invalid_request", "Provide a confirmed manuscript or owned images."
        )
    for material in materials:
        if (
            material["kind"] == "script"
            and len(material.get("data", {}).get("scenes", [])) > 60
        ):
            raise creation_error(
                422, "invalid_request", "The script scope exceeds 60 scenes."
            )
        source = material.get("source", {})
        duration = source.get("duration_ms")
        start, end = options.get("start_ms", 0), options.get("end_ms", duration)
        if duration is not None and (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= duration
        ):
            raise creation_error(
                422,
                "invalid_request",
                "The selected source interval is empty or out of bounds.",
            )
    if skill_id == "article-edit" and options.get("mode", "format") not in {
        "format",
        "polish",
        "restructure",
        "compress",
    }:
        raise creation_error(
            422, "invalid_request", "Choose an explicit article editing mode."
        )
