from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError

from app.api.admission import RateLimitAdmission
from app.api.deps import (
    IdempotencyKey,
    get_analysis_use_cases,
    get_current_user,
    get_history_record_service,
)
from app.api.responses import ApiResponseRoute
from app.core.runtime import AnalysisUseCases
from app.schemas.analyses import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisSkillResponse,
)
from app.schemas.history_records import (
    AnalysisRunHistoryPageResponse,
    AnalysisRunHistoryResponse,
    ContentCreationHistoryRecordResponse,
    HistoryRecordPageResponse,
    ScreenplayAnalysisHistoryRecordResponse,
    SkillAnalysisHistoryRecordResponse,
    VideoAnalysisHistoryRecordResponse,
)
from app.services.analysis.export_report import DOCX_MEDIA_TYPE, MARKDOWN_MEDIA_TYPE
from app.services.analysis.rules.enums import AnalysisInputKind
from app.services.auth.models import CurrentUser
from app.services.history_records import HistoryRecordPage, HistoryRecordService

router = APIRouter(route_class=ApiResponseRoute, tags=["analyses"])
User = Annotated[CurrentUser, Depends(get_current_user)]
UseCases = Annotated[AnalysisUseCases, Depends(get_analysis_use_cases)]


@router.get(
    "/analysis-skills",
    operation_id="listAnalysisSkills",
    response_model=tuple[AnalysisSkillResponse, ...],
    summary="列出输入兼容的分析 Skill",
)
async def list_analysis_skills(
    use_cases: UseCases,
    input_kind: AnalysisInputKind,
) -> tuple[AnalysisSkillResponse, ...]:
    return tuple(
        AnalysisSkillResponse.model_validate(skill)
        for skill in use_cases.list_analysis_skills(input_kind)
    )


@router.post(
    "/downloads/{download_id}/analyses",
    operation_id="createAnalysis",
    response_model=AnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimitAdmission("analysis"))],
    summary="创建视频分析任务",
)
async def create_analysis(
    download_id: UUID,
    body: AnalysisRequest,
    idempotency_key: IdempotencyKey,
    response: Response,
    user: User,
    use_cases: UseCases,
) -> AnalysisResponse:
    view = await use_cases.create_analysis(
        download_id,
        user.owner_hash,
        idempotency_key,
        body.skill_id,
        body.output_language,
        body.custom_prompt,
        quota=user.admission_quota,
    )
    response.headers["Location"] = f"/api/analyses/{view.id}"
    response.headers["Cache-Control"] = "private, no-store"
    return AnalysisResponse.from_view(view)


@router.post(
    "/analyses/{analysis_id}/retry",
    operation_id="retryAnalysis",
    response_model=AnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimitAdmission("analysis_retry"))],
    summary="重新执行原分析任务",
)
async def retry_analysis(
    analysis_id: UUID,
    request: Request,
    idempotency_key: IdempotencyKey,
    response: Response,
    user: User,
    use_cases: UseCases,
) -> AnalysisResponse:
    if (await request.body()).strip() not in {b"", b"null"}:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body",),
                    "msg": "Retry does not accept a request body",
                    "input": None,
                }
            ]
        )
    view = await use_cases.retry_analysis(
        analysis_id,
        user.owner_hash,
        idempotency_key,
        quota=user.admission_quota,
    )
    response.headers["Location"] = f"/api/analyses/{view.id}"
    response.headers["Cache-Control"] = "private, no-store"
    return AnalysisResponse.from_view(view)


@router.get(
    "/downloads/{download_id}/analysis",
    operation_id="getLatestDownloadAnalysis",
    response_model=AnalysisResponse | None,
    summary="读取下载任务最近的视频分析",
)
async def get_latest_download_analysis(
    download_id: UUID,
    user: User,
    use_cases: UseCases,
) -> AnalysisResponse | None:
    """恢复当前用户在该下载任务上最近创建的分析与报告。"""
    view = await use_cases.get_latest_download_analysis(download_id, user.owner_hash)
    return None if view is None else AnalysisResponse.from_view(view)


@router.get(
    "/analyses/{analysis_id}",
    operation_id="getAnalysis",
    response_model=AnalysisResponse,
    summary="查询分析任务",
)
async def get_analysis(
    analysis_id: UUID,
    user: User,
    use_cases: UseCases,
) -> AnalysisResponse:
    """查询分析进度及经过证据校验的结果。"""
    view = await use_cases.get_analysis(analysis_id, user.owner_hash)
    return AnalysisResponse.from_view(view)


@router.get(
    "/analyses/{analysis_id}/report.md",
    operation_id="exportAnalysisMarkdown",
    response_class=Response,
    responses={
        200: {
            "description": "Canonical Markdown analysis report",
            "content": {
                "text/markdown": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
    summary="导出 Markdown 分析报告",
)
async def export_analysis_markdown(
    analysis_id: UUID,
    user: User,
    use_cases: UseCases,
) -> Response:
    """导出与前端预览、DOCX 转换共用的唯一 Markdown 报告。"""
    report = await use_cases.export_analysis_markdown(analysis_id, user.owner_hash)
    return Response(
        content=report.content,
        media_type=MARKDOWN_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{report.filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/analyses/{analysis_id}/report.docx",
    operation_id="exportAnalysisReport",
    response_class=Response,
    responses={
        200: {
            "description": "Microsoft Word analysis report",
            "content": {
                DOCX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
    summary="导出视频分析报告",
)
async def export_analysis_report(
    analysis_id: UUID,
    user: User,
    use_cases: UseCases,
) -> Response:
    """将已完成的结构化分析结果导出为 DOCX 报告。"""
    report = await use_cases.export_analysis_report(analysis_id, user.owner_hash)
    return Response(
        content=report.content,
        media_type=report.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{report.filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/analyses/{analysis_id}/report.{report_format}",
    operation_id="exportAnalysisNativeReport",
    response_class=Response,
    summary="导出原生 Skill 报告",
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
async def export_analysis_native_report(
    analysis_id: UUID,
    report_format: Literal["html", "zip"],
    user: User,
    use_cases: UseCases,
) -> Response:
    report = await use_cases.export_analysis_markdown(
        analysis_id, user.owner_hash, report_format=report_format
    )
    return Response(
        content=report.content,
        media_type=report.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{report.filename}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "sandbox; default-src 'none'; img-src data:; "
                "style-src 'unsafe-inline'; script-src 'none'"
            ),
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/analyses/{analysis_id}/cancel",
    operation_id="cancelAnalysis",
    response_model=AnalysisResponse,
    summary="取消视频分析任务",
)
async def cancel_analysis(
    analysis_id: UUID,
    user: User,
    use_cases: UseCases,
) -> AnalysisResponse:
    """请求取消尚未结束的视频分析任务。"""
    view = await use_cases.cancel_analysis(analysis_id, user.owner_hash)
    return AnalysisResponse.from_view(view)


@router.delete(
    "/analyses/{analysis_id}",
    operation_id="deleteAnalysis",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除视频分析与报告",
)
async def delete_analysis(
    analysis_id: UUID,
    user: User,
    use_cases: UseCases,
) -> Response:
    """隐藏分析任务并异步清理其私有报告对象。"""
    await use_cases.delete_analysis(analysis_id, user.owner_hash)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/analyses/{analysis_id}/history-record",
    operation_id="getAnalysisHistoryRecord",
    response_model=VideoAnalysisHistoryRecordResponse
    | ScreenplayAnalysisHistoryRecordResponse
    | ContentCreationHistoryRecordResponse
    | SkillAnalysisHistoryRecordResponse,
    summary="读取分析来源与历史摘要",
)
async def get_analysis_history_record(
    analysis_id: UUID,
    user: User,
    service: Annotated[HistoryRecordService, Depends(get_history_record_service)],
    response: Response,
) -> (
    VideoAnalysisHistoryRecordResponse
    | ScreenplayAnalysisHistoryRecordResponse
    | ContentCreationHistoryRecordResponse
    | SkillAnalysisHistoryRecordResponse
):
    response.headers["Cache-Control"] = "no-store"
    record = await service.analysis_record(user.owner_hash, analysis_id)
    item = HistoryRecordPageResponse.from_page(
        HistoryRecordPage((record,), None)
    ).items[0]
    assert isinstance(
        item,
        VideoAnalysisHistoryRecordResponse
        | ScreenplayAnalysisHistoryRecordResponse
        | ContentCreationHistoryRecordResponse
        | SkillAnalysisHistoryRecordResponse,
    )
    return item


@router.get(
    "/analyses/{analysis_id}/runs",
    operation_id="listAnalysisRuns",
    response_model=AnalysisRunHistoryPageResponse,
    summary="分页读取分析运行记录",
)
async def list_analysis_runs(
    analysis_id: UUID,
    user: User,
    service: Annotated[HistoryRecordService, Depends(get_history_record_service)],
    response: Response,
    before_run_no: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> AnalysisRunHistoryPageResponse:
    response.headers["Cache-Control"] = "no-store"
    runs = await service.runs(
        user.owner_hash, analysis_id, before_run_no=before_run_no, limit=limit + 1
    )
    return AnalysisRunHistoryPageResponse(
        items=[
            AnalysisRunHistoryResponse.model_validate(run, from_attributes=True)
            for run in runs[:limit]
        ],
        next_before_run_no=runs[limit - 1].run_no if len(runs) > limit else None,
    )
