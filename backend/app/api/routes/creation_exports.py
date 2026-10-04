"""Revision-bound binary creation artifacts, using the same owner transport."""

import hashlib
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.deps import get_creation_export_service, get_current_user
from app.api.responses import ApiResponseRoute
from app.core.errors import AppError
from app.services.auth.models import CurrentUser
from app.services.creation.export_service import CreationExportService

router = APIRouter(prefix="/creation", route_class=ApiResponseRoute, tags=["creation"])


@router.get(
    "/tasks/{task_id}/revisions/{revision_id}/export/{format}",
    operation_id="exportCreationRevision",
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
async def export_creation_revision(
    task_id: UUID,
    revision_id: UUID,
    format: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[CreationExportService, Depends(get_creation_export_service)],
) -> Response:
    try:
        artifact = await service.export(task_id, revision_id, format, user.owner_hash)
    except ValueError:
        raise AppError(
            status=422,
            code="invalid_request",
            title="Export unavailable",
            detail=(
                "The saved revision cannot be exported in that format. "
                "Check its resources and local font configuration."
            ),
        ) from None
    return Response(
        artifact.data,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(artifact.filename),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Content-SHA256": hashlib.sha256(artifact.data).hexdigest(),
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
