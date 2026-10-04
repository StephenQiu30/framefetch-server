"""Business persistence operations implemented by the PostgreSQL repository."""

from typing import Any, Protocol
from uuid import UUID

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
)


class CreationPersistence(Protocol):
    async def runtime_availability(
        self, *, stale_seconds: int = 30
    ) -> tuple[bool, bool]: ...
    async def create_project(
        self, owner_hash: str, key: str, request: CreationProjectCreateRequest
    ) -> CreationProjectResponse: ...
    async def list_projects(
        self, owner_hash: str, limit: int = 50
    ) -> tuple[CreationProjectResponse, ...]: ...
    async def create_material(
        self,
        owner_hash: str,
        key: str,
        request: CreationMaterialCreateRequest,
        *,
        file_bytes: bytes | None = None,
        text_value: str | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> CreationMaterialResponse: ...
    async def list_materials(
        self, owner_hash: str, project_id: UUID | None = None, limit: int = 50
    ) -> tuple[CreationMaterialResponse, ...]: ...
    async def get_material(
        self, material_id: UUID, owner_hash: str
    ) -> CreationMaterialResponse: ...
    async def get_image(
        self, material_id: UUID, owner_hash: str
    ) -> tuple[bytes, str]: ...
    async def get_document_source(
        self, material_id: UUID, owner_hash: str
    ) -> tuple[bytes, str, str]: ...
    async def list_material_revisions(
        self, material_id: UUID, owner_hash: str
    ) -> tuple[CreationRevisionResponse, ...]: ...
    async def material_revisions(
        self, revision_ids: list[str], owner_hash: str
    ) -> list[dict[str, Any]]: ...
    async def save_material_revision(
        self,
        material_id: UUID,
        owner_hash: str,
        key: str,
        request: CreationRevisionSaveRequest,
    ) -> CreationMaterialResponse: ...
    async def confirm_material(
        self, material_id: UUID, owner_hash: str, request: CreationConfirmRequest
    ) -> CreationMaterialResponse: ...
    async def replay_task(
        self, owner_hash: str, key: str, request: CreationTaskCreateRequest
    ) -> CreationTaskResponse | None: ...
    async def create_task(
        self,
        owner_hash: str,
        key: str,
        request: CreationTaskCreateRequest,
        method_sha256: str,
    ) -> CreationTaskResponse: ...
    async def list_tasks(
        self,
        owner_hash: str,
        project_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> tuple[CreationTaskResponse, ...]: ...
    async def get_task(
        self, task_id: UUID, owner_hash: str | None = None
    ) -> CreationTaskResponse: ...
    async def cancel_task(
        self, task_id: UUID, owner_hash: str
    ) -> CreationTaskResponse: ...
    async def list_task_revisions(
        self, task_id: UUID, owner_hash: str
    ) -> tuple[CreationRevisionResponse, ...]: ...
    async def get_task_revision(
        self, task_id: UUID, revision_id: UUID, owner_hash: str
    ) -> CreationRevisionResponse: ...
    async def save_task_revision(
        self,
        task_id: UUID,
        owner_hash: str,
        key: str,
        request: CreationRevisionSaveRequest,
    ) -> CreationTaskResponse: ...
    async def confirm_task(
        self, task_id: UUID, owner_hash: str, request: CreationConfirmRequest
    ) -> CreationTaskResponse: ...
    async def retry_task(
        self, task_id: UUID, owner_hash: str, key: str
    ) -> CreationTaskResponse: ...
