from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import AwareDatetime

from app.api.admission import RateLimitAdmission
from app.api.deps import (
    IdempotencyKey,
    get_current_user,
    get_history_record_service,
    get_services,
    require_service,
)
from app.api.responses import ApiResponseRoute
from app.schemas.download_intents import (
    IntentHistoryResponse,
    IntentRequest,
    IntentResponse,
    IntentResumeRequest,
)
from app.schemas.history_records import HistoryRecordPageResponse
from app.services.analysis.rules.enums import AnalysisResultContract
from app.services.auth.models import CurrentUser
from app.services.downloads.intents import IntentService
from app.services.history_records import (
    HistoryRecordCursor,
    HistoryRecordFilters,
    HistoryRecordKind,
    HistoryRecordService,
    HistoryStatusGroup,
)

router = APIRouter(
    route_class=ApiResponseRoute, prefix="/download-intents", tags=["download-intents"]
)


def get_intent_service(request: Request) -> IntentService:
    return require_service(get_services(request).intent_service, "parse intent")


User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[IntentService, Depends(get_intent_service)]
HistoryService = Annotated[HistoryRecordService, Depends(get_history_record_service)]


@router.get(
    "",
    response_model=IntentResponse,
    operation_id="findDownloadIntent",
    summary="按幂等键找回当前用户已提交的解析意图",
)
async def find_intent(
    idempotency_key: Annotated[str, Query(min_length=1, max_length=128)],
    user: User,
    service: Service,
    response: Response,
) -> IntentResponse:
    response.headers["Cache-Control"] = "no-store"
    return IntentResponse.from_snapshot(
        await service.get_by_key(idempotency_key, user.owner_hash)
    )


@router.post(
    "",
    status_code=202,
    response_model=IntentResponse,
    operation_id="createDownloadIntent",
    dependencies=[Depends(RateLimitAdmission("inspect"))],
    summary="提交持久解析意图",
)
async def create_intent(
    body: IntentRequest,
    idempotency_key: IdempotencyKey,
    user: User,
    service: Service,
    response: Response,
) -> IntentResponse:
    result = await service.create(
        body.input, user.owner_hash, idempotency_key, quota=user.admission_quota
    )
    response.headers["Location"] = f"/api/download-intents/{result.id}"
    response.headers["Cache-Control"] = "no-store"
    return IntentResponse.from_snapshot(result)


@router.get(
    "/history",
    response_model=IntentHistoryResponse,
    operation_id="listDownloadIntents",
    summary="分页查询当前用户的解析记录",
)
async def list_intents(
    user: User,
    service: Service,
    response: Response,
    before: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> IntentHistoryResponse:
    response.headers["Cache-Control"] = "no-store"
    return IntentHistoryResponse.from_page(
        await service.history(user.owner_hash, before=before, limit=limit)
    )


@router.get(
    "/history/records",
    response_model=HistoryRecordPageResponse,
    operation_id="listHistoryRecords",
    summary="分页查询链接、视频 AI、剧本基础解析与剧本 AI 记录",
)
async def list_history_records(
    user: User,
    service: HistoryService,
    response: Response,
    before_created_at: AwareDatetime | None = None,
    record_type: Annotated[list[HistoryRecordKind] | None, Query()] = None,
    status_group: HistoryStatusGroup | None = None,
    created_from: AwareDatetime | None = None,
    created_to: AwareDatetime | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    skill_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    result_contract: AnalysisResultContract | None = None,
    document_id: UUID | None = None,
    download_id: UUID | None = None,
    before_record_type: HistoryRecordKind | None = None,
    before_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> HistoryRecordPageResponse:
    response.headers["Cache-Control"] = "no-store"
    if created_from and created_to and created_from >= created_to:
        raise HTTPException(
            status_code=422, detail="created_from must precede created_to"
        )
    kinds = tuple(record_type or ())
    if document_id and download_id:
        raise HTTPException(status_code=422, detail="Choose one source filter")
    if (
        (skill_id or result_contract)
        and kinds
        and not any(
            kind
            in {HistoryRecordKind.VIDEO_ANALYSIS, HistoryRecordKind.SCREENPLAY_ANALYSIS}
            for kind in kinds
        )
    ):
        raise HTTPException(
            status_code=422, detail="AI filters require analysis records"
        )
    cursor_parts = (before_created_at, before_record_type, before_id)
    if any(part is not None for part in cursor_parts) and not all(
        part is not None for part in cursor_parts
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "before_created_at, before_record_type and before_id "
                "are required together"
            ),
        )
    if before_created_at is None:
        before = None
    else:
        if before_record_type is None or before_id is None:
            raise HTTPException(
                status_code=422,
                detail="Incomplete history cursor",
            )
        before = HistoryRecordCursor(
            created_at=before_created_at,
            record_type=before_record_type,
            id=before_id,
        )
    return HistoryRecordPageResponse.from_page(
        await service.list(
            user.owner_hash,
            before=before,
            limit=limit,
            filters=HistoryRecordFilters(
                record_types=kinds,
                status_group=status_group,
                created_from=created_from,
                created_to=created_to,
                q=q.strip() if q else None,
                skill_id=skill_id,
                result_contract=result_contract,
                document_id=document_id,
                download_id=download_id,
            ),
        )
    )


@router.get(
    "/{intent_id}",
    response_model=IntentResponse,
    operation_id="getDownloadIntent",
    summary="查询当前用户的解析意图",
)
async def get_intent(
    intent_id: UUID, user: User, service: Service, response: Response
) -> IntentResponse:
    response.headers["Cache-Control"] = "no-store"
    return IntentResponse.from_snapshot(await service.get(intent_id, user.owner_hash))


@router.post(
    "/{intent_id}/refresh",
    status_code=202,
    response_model=IntentResponse,
    operation_id="refreshDownloadIntent",
    dependencies=[Depends(RateLimitAdmission("inspect"))],
    summary="在原意图与剩余预算内更新过期解析结果",
)
async def refresh_intent(
    intent_id: UUID, user: User, service: Service, response: Response
) -> IntentResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = f"/api/download-intents/{intent_id}"
    return IntentResponse.from_snapshot(
        await service.refresh(intent_id, user.owner_hash, quota=user.admission_quota)
    )


@router.post(
    "/{intent_id}/cancel",
    response_model=IntentResponse,
    operation_id="cancelDownloadIntent",
    summary="取消当前用户的解析意图",
)
async def cancel_intent(
    intent_id: UUID, user: User, service: Service, response: Response
) -> IntentResponse:
    response.headers["Cache-Control"] = "no-store"
    return IntentResponse.from_snapshot(
        await service.cancel(intent_id, user.owner_hash)
    )


@router.post(
    "/{intent_id}/resume",
    status_code=202,
    response_model=IntentResponse,
    operation_id="resumeDownloadIntent",
    dependencies=[Depends(RateLimitAdmission("inspect"))],
    summary="完成登录后继续原解析任务并重新验证来源",
)
async def resume_intent(
    intent_id: UUID,
    body: IntentResumeRequest,
    user: User,
    service: Service,
    response: Response,
) -> IntentResponse:
    response.headers["Cache-Control"] = "no-store"
    return IntentResponse.from_snapshot(
        await service.resume(intent_id, user.owner_hash, body.authorization_id)
    )


@router.post(
    "/{intent_id}/login",
    status_code=204,
    operation_id="openDownloadIntentLogin",
    dependencies=[Depends(RateLimitAdmission("inspect"))],
    summary="打开当前任务的平台专用登录浏览器",
)
async def open_intent_login(
    intent_id: UUID, body: IntentResumeRequest, user: User, service: Service
) -> Response:
    await service.login(intent_id, user.owner_hash, body.authorization_id)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
