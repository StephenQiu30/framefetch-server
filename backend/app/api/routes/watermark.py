"""Owner-only derived videos, independent of original download status."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.api.deps import IdempotencyKey, get_services, require_service
from app.api.responses import ApiResponseRoute
from app.api.routes.downloads import DownloadStorage, User, _parse_range
from app.repositories.watermark import WatermarkRepository
from app.schemas.watermark import (
    WatermarkListResponse,
    WatermarkTaskResponse,
)

router = APIRouter(route_class=ApiResponseRoute, tags=["downloads"])


def repository(request: Request) -> WatermarkRepository:
    return require_service(get_services(request).watermark_repository, "watermark")


Repository = Annotated[WatermarkRepository, Depends(repository)]


@router.get(
    "/downloads/{job_id}/watermarks",
    operation_id="listWatermarkTasks",
    response_model=WatermarkListResponse,
)
async def list_tasks(
    job_id: UUID, user: User, repo: Repository
) -> WatermarkListResponse:
    return await repo.for_job(job_id, user.owner_hash)


@router.post(
    "/downloads/{job_id}/watermarks",
    operation_id="createWatermarkTask",
    response_model=WatermarkTaskResponse,
    status_code=201,
)
async def create_task(
    job_id: UUID,
    idempotency_key: IdempotencyKey,
    user: User,
    repo: Repository,
) -> WatermarkTaskResponse:
    return await repo.create(
        job_id, user.owner_hash, idempotency_key, user.admission_quota
    )


@router.delete(
    "/watermarks/{task_id}", operation_id="cancelWatermarkTask", status_code=204
)
async def cancel_task(task_id: UUID, user: User, repo: Repository) -> Response:
    await repo.cancel(task_id, user.owner_hash)
    return Response(status_code=204)


@router.head("/watermarks/{task_id}/file", include_in_schema=False)
@router.get(
    "/watermarks/{task_id}/file",
    operation_id="getWatermarkFile",
    response_class=StreamingResponse,
)
async def get_file(
    task_id: UUID,
    request: Request,
    user: User,
    repo: Repository,
    storage: DownloadStorage,
    preview: Annotated[bool, Query()] = False,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    task, _ = await repo.artifact(task_id, user.owner_hash)
    selected = _parse_range(range_header, task.size_bytes)
    if range_header is not None and selected is None:
        return Response(
            status_code=416, headers={"Content-Range": f"bytes */{task.size_bytes}"}
        )
    start, end = selected or (0, task.size_bytes - 1)
    length = end - start + 1
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Content-Length": str(length),
        "Content-Disposition": "inline"
        if preview
        else f'attachment; filename="processed-{task.id}.mp4"',
        "ETag": f'"{task.sha256}"',
        "X-Content-Type-Options": "nosniff",
    }
    if selected:
        headers["Content-Range"] = f"bytes {start}-{end}/{task.size_bytes}"
    if request.method == "HEAD":
        return Response(
            status_code=206 if selected else 200,
            headers=headers,
            media_type="video/mp4",
        )
    assert task.object_key is not None
    return StreamingResponse(
        storage.iter_download(task.object_key, offset=start, length=length),
        status_code=206 if selected else 200,
        media_type="video/mp4",
        headers=headers,
    )
