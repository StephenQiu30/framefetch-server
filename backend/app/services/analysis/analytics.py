from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta

from app.services.analysis.analytics_models import (
    AnalysisAnalyticsDaily,
    AnalysisAnalyticsInput,
    AnalysisAnalyticsView,
)
from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
)
from app.services.analysis.ports import AnalysisRepository
from app.services.analysis.rules.enums import AnalysisInputKind
from app.services.analysis.validation import validate_now
from app.services.auth.errors import AuthError, AuthErrorCode
from app.services.auth.models import CurrentUser, UserRole


class GetAnalysisAnalytics:
    """Report retained execution runs, never infer supplier model requests."""

    def __init__(
        self, repository: AnalysisRepository, *, now: Callable[[], datetime]
    ) -> None:
        self._repository = repository
        self._now = now

    async def __call__(
        self, actor: CurrentUser, *, days: int = 30
    ) -> AnalysisAnalyticsView:
        if actor.role is not UserRole.ADMIN:
            raise AuthError(AuthErrorCode.FORBIDDEN)
        if not 7 <= days <= 365:
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.INVALID_REQUEST)
        end = validate_now(self._now()).astimezone(UTC)
        start = datetime.combine(
            end.date() - timedelta(days=days - 1), time.min, tzinfo=UTC
        )
        snapshot = await self._repository.get_analysis_analytics(start=start, end=end)
        by_date = {item.date: item for item in snapshot.daily}
        by_input = {item.input_kind: item for item in snapshot.inputs}
        return AnalysisAnalyticsView(
            period_days=days,
            start=start,
            end=end,
            summary=snapshot.summary,
            daily=tuple(
                by_date.get(current, AnalysisAnalyticsDaily(current, 0, 0, 0, 0, 0))
                for offset in range(days)
                for current in (start.date() + timedelta(days=offset),)
            ),
            inputs=tuple(
                by_input.get(kind, AnalysisAnalyticsInput(kind, 0))
                for kind in AnalysisInputKind
            ),
        )
