"""Owner-scoped creation materials, tasks and explicit human revisions."""

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.admission import RateLimitAdmission
from app.api.deps import IdempotencyKey, get_creation_service, get_current_user
from app.api.responses import ApiResponseRoute
from app.schemas.creation import (
    CreationConfirmRequest,
    CreationMaterialCreateRequest,
    CreationMaterialResponse,
    CreationProjectCreateRequest,
    CreationProjectResponse,
    CreationRetryRequest,
    CreationRevisionResponse,
    CreationRevisionSaveRequest,
    CreationSkillResponse,
    CreationTaskCreateRequest,
    CreationTaskResponse,
    CreationTaskStatus,
)
from app.services.auth.models import CurrentUser
from app.services.creation.service import CreationService

router = APIRouter(prefix="/creation", route_class=ApiResponseRoute, tags=["creation"])
User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[CreationService, Depends(get_creation_service)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get(
    "/skills",
    operation_id="listCreationSkills",
    response_model=tuple[CreationSkillResponse, ...],
)
async def list_creation_skills(
    user: User, service: Service
) -> tuple[CreationSkillResponse, ...]:
    return await service.list_skills()


@router.post(
    "/projects",
    operation_id="createCreationProject",
    status_code=201,
    response_model=CreationProjectResponse,
)
async def create_creation_project(
    body: CreationProjectCreateRequest,
    idempotency_key: IdempotencyKey,
    user: User,
    service: Service,
) -> CreationProjectResponse:
    return await service.create_project(user.owner_hash, idempotency_key, body)


@router.get(
    "/projects",
    operation_id="listCreationProjects",
    response_model=tuple[CreationProjectResponse, ...],
)
async def list_creation_projects(
    user: User, service: Service, limit: Limit = 50
) -> tuple[CreationProjectResponse, ...]:
    return await service.list_projects(user.owner_hash, limit)


@router.post(
    "/materials",
    operation_id="createCreationMaterial",
    status_code=201,
    response_model=CreationMaterialResponse,
)
async def create_creation_material(
    body: CreationMaterialCreateRequest,
    idempotency_key: IdempotencyKey,
    user: User,
    service: Service,
) -> CreationMaterialResponse:
    return await service.create_material(user.owner_hash, idempotency_key, body)


@router.get(
    "/materials",
    operation_id="listCreationMaterials",
    response_model=tuple[CreationMaterialResponse, ...],
)
async def list_creation_materials(
    user: User, service: Service, project_id: UUID | None = None, limit: Limit = 50
) -> tuple[CreationMaterialResponse, ...]:
    return await service.list_materials(user.owner_hash, project_id, limit)


@router.get(
    "/materials/{material_id}",
    operation_id="getCreationMaterial",
    response_model=CreationMaterialResponse,
)
async def get_creation_material(
    material_id: UUID, user: User, service: Service
) -> CreationMaterialResponse:
    return await service.get_material(material_id, user.owner_hash)


@router.get(
    "/materials/{material_id}/revisions",
    operation_id="listCreationMaterialRevisions",
    response_model=tuple[CreationRevisionResponse, ...],
)
async def list_creation_material_revisions(
    material_id: UUID, user: User, service: Service
) -> tuple[CreationRevisionResponse, ...]:
    return await service.list_material_revisions(material_id, user.owner_hash)


@router.get(
    "/materials/{material_id}/image",
    operation_id="getCreationMaterialImage",
    response_class=Response,
    response_model=None,
    responses={
        200: {
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            }
        }
    },
)
async def get_creation_material_image(
    material_id: UUID, user: User, service: Service
) -> Response:
    content, media_type = await service.repository.get_image(
        material_id, user.owner_hash
    )
    return Response(
        content,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/materials/{material_id}/source",
    operation_id="getCreationDocumentSource",
    response_class=Response,
    response_model=None,
    responses={
        200: {
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            }
        }
    },
)
async def get_creation_document_source(
    material_id: UUID, user: User, service: Service
) -> Response:
    content, media_type, filename = await service.repository.get_document_source(
        material_id, user.owner_hash
    )
    return Response(
        content,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename),
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.post(
    "/materials/{material_id}/revisions",
    operation_id="saveCreationMaterialRevision",
    response_model=CreationMaterialResponse,
)
async def save_creation_material_revision(
    material_id: UUID,
    body: CreationRevisionSaveRequest,
    idempotency_key: IdempotencyKey,
    user: User,
    service: Service,
) -> CreationMaterialResponse:
    return await service.save_material_revision(
        material_id, user.owner_hash, idempotency_key, body
    )


@router.post(
    "/materials/{material_id}/confirm",
    operation_id="confirmCreationMaterial",
    response_model=CreationMaterialResponse,
)
async def confirm_creation_material(
    material_id: UUID, body: CreationConfirmRequest, user: User, service: Service
) -> CreationMaterialResponse:
    return await service.confirm_material(material_id, user.owner_hash, body)


@router.post(
    "/tasks",
    operation_id="createCreationTask",
    status_code=201,
    response_model=CreationTaskResponse,
    dependencies=[Depends(RateLimitAdmission("analysis"))],
)
async def create_creation_task(
    body: CreationTaskCreateRequest,
    idempotency_key: IdempotencyKey,
    user: User,
    service: Service,
) -> CreationTaskResponse:
    return await service.create_task(user.owner_hash, idempotency_key, body)


@router.get(
    "/tasks",
    operation_id="listCreationTasks",
    response_model=tuple[CreationTaskResponse, ...],
)
async def list_creation_tasks(
    user: User,
    service: Service,
    project_id: UUID | None = None,
    status: CreationTaskStatus | None = None,
    limit: Limit = 50,
) -> tuple[CreationTaskResponse, ...]:
    return await service.list_tasks(user.owner_hash, project_id, status, limit)


@router.get(
    "/tasks/{task_id}",
    operation_id="getCreationTask",
    response_model=CreationTaskResponse,
)
async def get_creation_task(
    task_id: UUID, user: User, service: Service
) -> CreationTaskResponse:
    return await service.get_task(task_id, user.owner_hash)


@router.post(
    "/tasks/{task_id}/cancel",
    operation_id="cancelCreationTask",
    response_model=CreationTaskResponse,
)
async def cancel_creation_task(
    task_id: UUID, user: User, service: Service
) -> CreationTaskResponse:
    return await service.cancel_task(task_id, user.owner_hash)


@router.get(
    "/tasks/{task_id}/revisions",
    operation_id="listCreationTaskRevisions",
    response_model=tuple[CreationRevisionResponse, ...],
)
async def list_creation_task_revisions(
    task_id: UUID, user: User, service: Service
) -> tuple[CreationRevisionResponse, ...]:
    return await service.list_task_revisions(task_id, user.owner_hash)


@router.post(
    "/tasks/{task_id}/revisions",
    operation_id="saveCreationTaskRevision",
    response_model=CreationTaskResponse,
)
async def save_creation_task_revision(
    task_id: UUID,
    body: CreationRevisionSaveRequest,
    idempotency_key: IdempotencyKey,
    user: User,
    service: Service,
) -> CreationTaskResponse:
    return await service.save_task_revision(
        task_id, user.owner_hash, idempotency_key, body
    )


@router.post(
    "/tasks/{task_id}/confirm",
    operation_id="confirmCreationTask",
    response_model=CreationTaskResponse,
)
async def confirm_creation_task(
    task_id: UUID, body: CreationConfirmRequest, user: User, service: Service
) -> CreationTaskResponse:
    return await service.confirm_task(task_id, user.owner_hash, body)


@router.post(
    "/tasks/{task_id}/attempts",
    operation_id="retryCreationTask",
    dependencies=[Depends(RateLimitAdmission("analysis_retry"))],
    response_model=CreationTaskResponse,
)
async def retry_creation_task(
    task_id: UUID,
    body: CreationRetryRequest,
    idempotency_key: IdempotencyKey,
    user: User,
    service: Service,
) -> CreationTaskResponse:
    return await service.retry_task(task_id, user.owner_hash, idempotency_key)
