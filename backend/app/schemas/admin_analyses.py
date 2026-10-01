from __future__ import annotations

from datetime import date as Date
from datetime import datetime

from pydantic import Field

from app.schemas.common import StrictModel
from app.services.analysis.analytics_models import AnalysisAnalyticsView
from app.services.analysis.rules.enums import AnalysisInputKind


class AnalysisAnalyticsSummaryResponse(StrictModel):
    total: int = Field(ge=0, description="保留的分析执行次数，不代表模型请求次数。")
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    active: int = Field(ge=0, description="queued、running、retry_wait 的执行数量。")
    average_duration_seconds: float | None = Field(
        ge=0,
        description="终态执行的 finished_at-started_at 均值，包含重试与发布；"
        "只纳入两时间齐全且非负的样本，没有有效样本时为 null。",
    )
    completed_duration_count: int = Field(
        ge=0, description="平均执行耗时的有效终态样本数。"
    )


class AnalysisAnalyticsDailyResponse(StrictModel):
    date: Date = Field(description="执行 created_at 所属的 UTC 日期。")
    total: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    active: int = Field(ge=0)


class AnalysisAnalyticsInputResponse(StrictModel):
    input_kind: AnalysisInputKind
    total: int = Field(ge=0)


class AnalysisAnalyticsResponse(StrictModel):
    period_days: int = Field(ge=7, le=365)
    start: datetime = Field(description="UTC 窗口起始日零时，含此时刻。")
    end: datetime = Field(description="查询时刻，含此时刻。")
    summary: AnalysisAnalyticsSummaryResponse
    daily: list[AnalysisAnalyticsDailyResponse]
    inputs: list[AnalysisAnalyticsInputResponse]

    @classmethod
    def from_view(cls, view: AnalysisAnalyticsView) -> AnalysisAnalyticsResponse:
        return cls.model_validate(view)
