"""Read-only, bounded aggregates over retained analysis execution runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, func, select
from sqlalchemy.engine import Row
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from app.models import AnalysisJobRow, AnalysisRunRow
from app.repositories.repository_base import RepositoryBase
from app.services.analysis.analytics_models import (
    AnalysisAnalyticsDaily,
    AnalysisAnalyticsInput,
    AnalysisAnalyticsSnapshot,
    AnalysisAnalyticsSummary,
)
from app.services.analysis.rules.enums import AnalysisInputKind

_ACTIVE_STATUSES = ("queued", "running", "retry_wait")
_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


class AnalysisAnalyticsRepository(RepositoryBase):
    async def get_analysis_analytics(
        self, *, start: datetime, end: datetime
    ) -> AnalysisAnalyticsSnapshot:
        if start >= end:
            raise ValueError("analytics start must be before end")
        async with self._sessions() as session:
            # Keep all chart sections on one snapshot while runs change status.
            await session.connection(
                execution_options={"isolation_level": "REPEATABLE READ"}
            )
            summary = await session.execute(_summary_statement(start, end))
            daily = await session.execute(_daily_statement(start, end))
            inputs = await session.execute(_input_statement(start, end))
        return AnalysisAnalyticsSnapshot(
            summary=_summary(summary.one()),
            daily=tuple(_daily(row) for row in daily.all()),
            inputs=tuple(
                AnalysisAnalyticsInput(AnalysisInputKind(row.input_kind), row.total)
                for row in inputs.all()
            ),
        )


def _base_statement(start: datetime, end: datetime, *columns: Any) -> Select[Any]:
    # A job has many runs, so count run IDs. Soft deletion hides a job from
    # personal history but does not erase its retained execution history here.
    return (
        select(*columns)
        .select_from(AnalysisRunRow)
        .join(AnalysisJobRow, AnalysisJobRow.id == AnalysisRunRow.job_id)
        .where(AnalysisRunRow.created_at >= start, AnalysisRunRow.created_at <= end)
    )


def _counts() -> tuple[ColumnElement[int], ...]:
    return (
        func.count(AnalysisRunRow.id).label("total"),
        *(
            func.coalesce(
                func.sum(case((AnalysisRunRow.status == status, 1), else_=0)), 0
            ).label(status)
            for status in _TERMINAL_STATUSES
        ),
        func.coalesce(
            func.sum(case((AnalysisRunRow.status.in_(_ACTIVE_STATUSES), 1), else_=0)),
            0,
        ).label("active"),
    )


def _summary_statement(start: datetime, end: datetime) -> Select[Any]:
    valid_duration = and_(
        AnalysisRunRow.status.in_(_TERMINAL_STATUSES),
        AnalysisRunRow.started_at.is_not(None),
        AnalysisRunRow.finished_at.is_not(None),
        AnalysisRunRow.finished_at >= AnalysisRunRow.started_at,
    )
    duration = case(
        (
            valid_duration,
            func.extract(
                "epoch", AnalysisRunRow.finished_at - AnalysisRunRow.started_at
            ),
        ),
        else_=None,
    )
    return _base_statement(
        start,
        end,
        *_counts(),
        func.avg(duration).label("average_duration_seconds"),
        func.count(duration).label("completed_duration_count"),
    )


def _daily_statement(start: datetime, end: datetime) -> Select[Any]:
    day = func.date(func.timezone("UTC", AnalysisRunRow.created_at)).label("date")
    return _base_statement(start, end, day, *_counts()).group_by(day).order_by(day)


def _input_statement(start: datetime, end: datetime) -> Select[Any]:
    kind = AnalysisJobRow.input_kind.label("input_kind")
    return (
        _base_statement(start, end, kind, func.count(AnalysisRunRow.id).label("total"))
        .group_by(kind)
        .order_by(kind)
    )


def _summary(row: Row[Any]) -> AnalysisAnalyticsSummary:
    return AnalysisAnalyticsSummary(
        total=row.total,
        succeeded=row.succeeded,
        failed=row.failed,
        cancelled=row.cancelled,
        active=row.active,
        average_duration_seconds=(
            None
            if row.average_duration_seconds is None
            else round(float(row.average_duration_seconds), 2)
        ),
        completed_duration_count=row.completed_duration_count,
    )


def _daily(row: Row[Any]) -> AnalysisAnalyticsDaily:
    return AnalysisAnalyticsDaily(
        date=row.date,
        total=row.total,
        succeeded=row.succeeded,
        failed=row.failed,
        cancelled=row.cancelled,
        active=row.active,
    )
