from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import get_analysis_use_cases, get_current_admin
from app.api.responses import ApiResponseRoute
from app.core.runtime import AnalysisUseCases
from app.schemas.admin_analyses import AnalysisAnalyticsResponse
from app.services.auth.models import CurrentUser

router = APIRouter(
    route_class=ApiResponseRoute, prefix="/admin/analyses", tags=["admin"]
)
Admin = Annotated[CurrentUser, Depends(get_current_admin)]
UseCases = Annotated[AnalysisUseCases, Depends(get_analysis_use_cases)]


@router.get(
    "/analytics",
    operation_id="getAnalysisAnalytics",
    response_model=AnalysisAnalyticsResponse,
    summary="查询 AI 分析执行统计",
)
async def get_analysis_analytics(
    admin: Admin,
    use_cases: UseCases,
    response: Response,
    days: Annotated[int, Query(ge=7, le=365)] = 30,
) -> AnalysisAnalyticsResponse:
    """按每次 analysis_run 的 created_at UTC 自然日统计其当前状态。

    手动重试与重新分析各计一次执行；包含所属任务已软删除但数据库仍保留的
    执行记录。统计不代表供应商模型请求次数，不推算 token、费用或 Provider
    延迟。平均耗时只纳入有有效开始、结束时间的终态执行，包含执行内重试和
    报告发布；没有有效样本时返回 null。
    """
    view = await use_cases.get_analysis_analytics(admin, days=days)
    response.headers["Cache-Control"] = "no-store"
    return AnalysisAnalyticsResponse.from_view(view)
