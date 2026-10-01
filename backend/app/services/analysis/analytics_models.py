from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.services.analysis.rules.enums import AnalysisInputKind


@dataclass(frozen=True, slots=True)
class AnalysisAnalyticsSummary:
    total: int
    succeeded: int
    failed: int
    cancelled: int
    active: int
    average_duration_seconds: float | None
    completed_duration_count: int


@dataclass(frozen=True, slots=True)
class AnalysisAnalyticsDaily:
    date: date
    total: int
    succeeded: int
    failed: int
    cancelled: int
    active: int


@dataclass(frozen=True, slots=True)
class AnalysisAnalyticsInput:
    input_kind: AnalysisInputKind
    total: int


@dataclass(frozen=True, slots=True)
class AnalysisAnalyticsSnapshot:
    summary: AnalysisAnalyticsSummary
    daily: tuple[AnalysisAnalyticsDaily, ...]
    inputs: tuple[AnalysisAnalyticsInput, ...]


@dataclass(frozen=True, slots=True)
class AnalysisAnalyticsView:
    period_days: int
    start: datetime
    end: datetime
    summary: AnalysisAnalyticsSummary
    daily: tuple[AnalysisAnalyticsDaily, ...]
    inputs: tuple[AnalysisAnalyticsInput, ...]
