from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from app.services.analysis.analytics import GetAnalysisAnalytics
from app.services.analysis.analytics_models import (
    AnalysisAnalyticsDaily,
    AnalysisAnalyticsInput,
    AnalysisAnalyticsSnapshot,
    AnalysisAnalyticsSummary,
)
from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
)
from app.services.analysis.rules.enums import AnalysisInputKind
from app.services.auth.errors import AuthError, AuthErrorCode
from app.services.auth.models import CurrentUser, UserRole

NOW = datetime(2026, 8, 10, 12, 30, tzinfo=UTC)
ADMIN = CurrentUser(uuid4(), "admin", "admin@example.com", UserRole.ADMIN, NOW, NOW)
USER = replace(ADMIN, role=UserRole.USER)


class Repository:
    def __init__(self, snapshot: AnalysisAnalyticsSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[datetime, datetime]] = []

    async def get_analysis_analytics(
        self, *, start: datetime, end: datetime
    ) -> AnalysisAnalyticsSnapshot:
        self.calls.append((start, end))
        return self.snapshot


def snapshot(*, empty: bool = False) -> AnalysisAnalyticsSnapshot:
    return AnalysisAnalyticsSnapshot(
        summary=AnalysisAnalyticsSummary(
            total=0 if empty else 3,
            succeeded=0 if empty else 1,
            failed=0 if empty else 1,
            cancelled=0,
            active=0 if empty else 1,
            average_duration_seconds=None if empty else 12.5,
            completed_duration_count=0 if empty else 2,
        ),
        daily=()
        if empty
        else (AnalysisAnalyticsDaily(date(2026, 8, 8), 3, 1, 1, 0, 1),),
        inputs=() if empty else (AnalysisAnalyticsInput(AnalysisInputKind.VIDEO, 3),),
    )


@pytest.mark.asyncio
async def test_analysis_analytics_fills_utc_days_and_missing_input_kinds() -> None:
    repository = Repository(snapshot())
    # Local date is August 11, but the cohort window ends on August 10 UTC.
    clock = datetime(2026, 8, 11, 1, tzinfo=timezone(timedelta(hours=8)))
    use_case = GetAnalysisAnalytics(repository, now=lambda: clock)  # type: ignore[arg-type]

    view = await use_case(ADMIN, days=7)

    assert repository.calls == [
        (datetime(2026, 8, 4, tzinfo=UTC), datetime(2026, 8, 10, 17, tzinfo=UTC))
    ]
    assert len(view.daily) == 7
    assert view.daily[0] == AnalysisAnalyticsDaily(date(2026, 8, 4), 0, 0, 0, 0, 0)
    assert view.daily[4] == AnalysisAnalyticsDaily(date(2026, 8, 8), 3, 1, 1, 0, 1)
    assert view.daily[-1].date == date(2026, 8, 10)
    assert view.inputs == (
        AnalysisAnalyticsInput(AnalysisInputKind.VIDEO, 3),
        AnalysisAnalyticsInput(AnalysisInputKind.SCREENPLAY, 0),
        AnalysisAnalyticsInput(AnalysisInputKind.CONTENT, 0),
        AnalysisAnalyticsInput(AnalysisInputKind.SKILL, 0),
    )
    assert view.summary.average_duration_seconds == 12.5
    assert view.summary.completed_duration_count == 2


@pytest.mark.asyncio
async def test_empty_analysis_analytics_has_null_duration_and_real_zero_counts() -> (
    None
):
    repository = Repository(snapshot(empty=True))
    use_case = GetAnalysisAnalytics(repository, now=lambda: NOW)  # type: ignore[arg-type]

    view = await use_case(ADMIN, days=30)

    assert view.period_days == 30
    assert view.summary.average_duration_seconds is None
    assert view.summary.completed_duration_count == 0
    assert len(view.daily) == 30
    assert all(item.total == item.active == 0 for item in view.daily)
    assert [item.total for item in view.inputs] == [0, 0, 0, 0]


@pytest.mark.parametrize("days", [0, 6, 366])
@pytest.mark.asyncio
async def test_analysis_analytics_rejects_period_before_querying(days: int) -> None:
    repository = Repository(snapshot())
    use_case = GetAnalysisAnalytics(repository, now=lambda: NOW)  # type: ignore[arg-type]

    with pytest.raises(AnalysisApplicationError) as error:
        await use_case(ADMIN, days=days)

    assert error.value.code is AnalysisApplicationErrorCode.INVALID_REQUEST
    assert repository.calls == []


@pytest.mark.asyncio
async def test_analysis_analytics_rejects_non_admin_before_querying() -> None:
    repository = Repository(snapshot())
    use_case = GetAnalysisAnalytics(repository, now=lambda: NOW)  # type: ignore[arg-type]

    with pytest.raises(AuthError) as error:
        await use_case(USER)

    assert error.value.code is AuthErrorCode.FORBIDDEN
    assert repository.calls == []
