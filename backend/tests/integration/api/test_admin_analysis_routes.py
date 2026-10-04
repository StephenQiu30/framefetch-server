from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.api.deps import get_analysis_use_cases, get_current_user
from app.core.config import Settings
from app.main import create_app
from app.services.analysis.analytics import GetAnalysisAnalytics
from app.services.analysis.analytics_models import (
    AnalysisAnalyticsSnapshot,
    AnalysisAnalyticsSummary,
)
from app.services.auth.models import CurrentUser, UserRole
from fastapi import FastAPI
from fastapi.testclient import TestClient

NOW = datetime(2026, 8, 10, 12, 30, tzinfo=UTC)


class Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[datetime, datetime]] = []

    async def get_analysis_analytics(
        self, *, start: datetime, end: datetime
    ) -> AnalysisAnalyticsSnapshot:
        self.calls.append((start, end))
        return AnalysisAnalyticsSnapshot(
            summary=AnalysisAnalyticsSummary(0, 0, 0, 0, 0, None, 0),
            daily=(),
            inputs=(),
        )


def application(role: UserRole) -> tuple[FastAPI, Repository]:
    app = create_app(Settings(app_env="test", _env_file=None))
    repository = Repository()
    analytics = GetAnalysisAnalytics(repository, now=lambda: NOW)  # type: ignore[arg-type]
    app.dependency_overrides[get_analysis_use_cases] = lambda: SimpleNamespace(
        get_analysis_analytics=analytics
    )
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uuid4(), "analytics_user", "user@example.com", role, NOW, NOW
    )
    return app, repository


def test_admin_analysis_analytics_returns_only_aggregate_fields_without_caching() -> (
    None
):
    app, repository = application(UserRole.ADMIN)

    with TestClient(app) as client:
        response = client.get("/api/admin/analyses/analytics", params={"days": 7})

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.json()["data"]
    assert payload["summary"] == {
        "total": 0,
        "succeeded": 0,
        "failed": 0,
        "cancelled": 0,
        "active": 0,
        "average_duration_seconds": None,
        "completed_duration_count": 0,
    }
    assert len(payload["daily"]) == 7
    assert payload["inputs"] == [
        {"input_kind": "video", "total": 0},
        {"input_kind": "screenplay", "total": 0},
        {"input_kind": "content", "total": 0},
        {"input_kind": "skill", "total": 0},
    ]
    assert repository.calls == [(datetime(2026, 8, 4, tzinfo=UTC), NOW)]
    assert all(
        field not in response.text
        for field in (
            "owner_hash",
            "job_id",
            "provider",
            "model",
            "custom_prompt",
            "skill_instructions",
            "payload",
            "token",
            "cost",
        )
    )


def test_admin_analysis_analytics_checks_role_before_querying() -> None:
    app, repository = application(UserRole.USER)

    with TestClient(app) as client:
        response = client.get("/api/admin/analyses/analytics")

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert repository.calls == []


@pytest.mark.parametrize("days", [6, 366])
def test_admin_analysis_analytics_rejects_invalid_http_period(days: int) -> None:
    app, repository = application(UserRole.ADMIN)

    with TestClient(app) as client:
        response = client.get("/api/admin/analyses/analytics", params={"days": days})

    assert response.status_code == 422
    assert repository.calls == []
