from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.api.deps import get_current_user
from app.core.config import Settings
from app.core.runtime import AnalysisUseCases
from app.main import create_app
from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
)
from app.services.analysis.export_report import DOCX_MEDIA_TYPE, MARKDOWN_MEDIA_TYPE
from app.services.analysis.models import (
    AnalysisJobView,
    AnalysisReportFile,
    AnalysisReportSnapshot,
)
from app.services.analysis.report import render_analysis_report_markdown
from app.services.analysis.rules.enums import (
    AnalysisInputKind,
    AnalysisReportStatus,
    AnalysisResultContract,
    AnalysisStatus,
)
from app.services.analysis.rules.result_items import Shot, VisualAsset
from app.services.analysis.rules.result_models import (
    AnalysisMedia,
    EvidenceSummary,
    ProductionAdvice,
    VideoAnalysisResult,
)
from app.services.analysis.rules.video_scene import VideoScene
from app.services.auth.models import CurrentUser, UserRole
from fastapi.testclient import TestClient

NOW = datetime(2026, 8, 6, 10, tzinfo=UTC)
DOWNLOAD_ID = UUID("44444444-4444-4444-8444-444444444444")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444445")
ANALYSIS_ID = UUID("55555555-5555-4555-8555-555555555555")
RESULT = VideoAnalysisResult(
    language="zh-CN",
    title="可验证视觉分析",
    summary=EvidenceSummary(text="摘要", evidence_shot_ids=("shot-1",)),
    media=AnalysisMedia(duration_ms=1_000, container="mp4", size_bytes=100),
    shot_count=1,
    shots=(
        Shot(
            id="shot-1",
            index=1,
            start_ms=0,
            end_ms=1_000,
            representative_frame_ms=500,
            description="开场画面",
            transition_in="none",
            shot_size="wide",
            camera_motion="static",
            narrative_function="建立故事空间。",
            highlight_score=3,
            visual_tags=("开场",),
            asset_ids=("asset-1",),
        ),
    ),
    scenes=(
        VideoScene(
            id="scene-1",
            index=1,
            title="开场建立",
            start_ms=0,
            end_ms=1_000,
            location="室内空间",
            description="单镜头建立开场空间。",
            narrative_function="建立故事空间。",
            visual_rules=("固定广角构图",),
            continuity_risks=(),
            evidence_shot_ids=("shot-1",),
        ),
    ),
    highlights=(),
    assets=(
        VisualAsset(
            id="asset-1",
            type="logo",
            label="示例标志",
            description="画面标志",
            first_seen_ms=0,
            evidence_shot_ids=("shot-1",),
        ),
    ),
    production_advice=ProductionAdvice(
        summary="优先还原开场镜头。",
        priority_shot_ids=("shot-1",),
        recommended_extensions=("镜头 Prompt",),
    ),
)
TEST_USER = CurrentUser(
    id=DOWNLOAD_ID,
    username="video_user",
    email="user@example.com",
    role=UserRole.USER,
    created_at=NOW,
    updated_at=NOW,
)


class StubUseCase:
    def __init__(self, result: object) -> None:
        self.result = result
        self.error: AnalysisApplicationError | None = None
        self.calls: list[tuple[object, ...]] = []

    async def __call__(self, *args: object, **_kwargs: object) -> object:
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.result


def analysis_view(
    status: AnalysisStatus = AnalysisStatus.QUEUED,
    *,
    result: VideoAnalysisResult | None = None,
) -> AnalysisJobView:
    report = (
        AnalysisReportSnapshot(
            id=ANALYSIS_ID,
            job_id=ANALYSIS_ID,
            run_id=ANALYSIS_ID,
            status=AnalysisReportStatus.AVAILABLE,
            markdown=render_analysis_report_markdown(result),
            content_sha256="a" * 64,
            renderer_version="analysis-report",
            created_at=NOW,
            published_at=NOW,
            artifacts=(),
        )
        if status is AnalysisStatus.SUCCEEDED and result is not None
        else None
    )
    return AnalysisJobView(
        id=ANALYSIS_ID,
        run_id=ANALYSIS_ID,
        run_no=1,
        run_trigger="initial",
        version=0,
        skill_id="director-breakdown",
        output_language="zh-CN",
        status=status,
        stage=None,
        progress=100 if status is AnalysisStatus.SUCCEEDED else 0,
        attempt=1 if status is AnalysisStatus.SUCCEEDED else 0,
        error_code=None,
        created_at=NOW,
        updated_at=NOW,
        finished_at=NOW if status is AnalysisStatus.SUCCEEDED else None,
        result=result,
        report=report,
        current_report_id=None if report is None else report.id,
    )


def client(tmp_path: Path) -> tuple[TestClient, dict[str, StubUseCase]]:
    application = create_app(Settings(app_env="test"))
    queued = analysis_view()
    stubs = {
        "create": StubUseCase(queued),
        "create_document": StubUseCase(
            replace(
                queued,
                skill_id="screenplay-analysis",
                input_kind=AnalysisInputKind.SCREENPLAY,
                result_contract=AnalysisResultContract.SCREENPLAY_ANALYSIS,
            )
        ),
        "get": StubUseCase(queued),
        "cancel": StubUseCase(
            replace(queued, status=AnalysisStatus.CANCELLED, finished_at=NOW)
        ),
        "retry": StubUseCase(replace(queued, run_no=2, run_trigger="manual_retry")),
        "delete": StubUseCase(None),
        "latest_document": StubUseCase(None),
    }
    application.state.services.analysis_use_cases = AnalysisUseCases(
        get_analysis_analytics=StubUseCase(None),
        list_analysis_skills=lambda _: (),
        create_analysis=stubs["create"],
        create_document_analysis=stubs["create_document"],
        retry_analysis=stubs["retry"],
        delete_analysis=stubs["delete"],
        get_analysis=stubs["get"],
        get_latest_download_analysis=stubs["get"],
        get_latest_document_analysis=stubs["latest_document"],
        cancel_analysis=stubs["cancel"],
        export_analysis_report=StubUseCase(
            AnalysisReportFile(
                content=b"docx fixture",
                filename=f"analysis-report-{ANALYSIS_ID}.docx",
                media_type=DOCX_MEDIA_TYPE,
            )
        ),
        export_analysis_markdown=StubUseCase(
            AnalysisReportFile(
                content=b"# markdown fixture\n",
                filename=f"analysis-report-{ANALYSIS_ID}.md",
                media_type=MARKDOWN_MEDIA_TYPE,
            )
        ),
    )
    application.dependency_overrides[get_current_user] = lambda: TEST_USER
    return TestClient(application), stubs


def test_analysis_service_must_be_wired(tmp_path: Path) -> None:
    application = create_app(Settings(app_env="test"))
    with TestClient(application) as test_client:
        response = test_client.get(f"/api/analyses/{ANALYSIS_ID}")

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"


def test_succeeded_analysis_returns_only_strict_structured_result(
    tmp_path: Path,
) -> None:
    test_client, stubs = client(tmp_path)
    stubs["get"].result = analysis_view(
        AnalysisStatus.SUCCEEDED,
        result=RESULT,
    )
    with test_client:
        response = test_client.get(f"/api/analyses/{ANALYSIS_ID}")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["result"]["kind"] == "video_visual_analysis"
    assert payload["result"]["shot_count"] == 1
    assert payload["result"]["scenes"][0]["evidence_shot_ids"] == ["shot-1"]
    assert payload["result"]["assets"][0]["evidence_shot_ids"] == ["shot-1"]
    assert payload["result"]["shots"][0]["narrative_function"] == "建立故事空间。"
    assert payload["result"]["production_advice"]["priority_shot_ids"] == ["shot-1"]
    assert payload["report_markdown"].startswith("# 可验证视觉分析")
    assert "schema_version" not in payload["result"]
    assert "transcript" not in response.text
    assert "provider" not in response.text


def test_completed_analysis_report_can_be_exported_as_docx(tmp_path: Path) -> None:
    test_client, _ = client(tmp_path)
    with test_client:
        response = test_client.get(f"/api/analyses/{ANALYSIS_ID}/report.docx")

    assert response.status_code == 200
    assert response.content == b"docx fixture"
    assert response.headers["content-type"] == DOCX_MEDIA_TYPE
    assert response.headers["content-disposition"] == (
        f'attachment; filename="analysis-report-{ANALYSIS_ID}.docx"'
    )
    assert response.headers["x-content-type-options"] == "nosniff"


def test_completed_analysis_report_can_be_exported_as_markdown(tmp_path: Path) -> None:
    test_client, _ = client(tmp_path)
    with test_client:
        response = test_client.get(f"/api/analyses/{ANALYSIS_ID}/report.md")

    assert response.status_code == 200
    assert response.content == b"# markdown fixture\n"
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="analysis-report-{ANALYSIS_ID}.md"'
    )


def test_analysis_errors_are_error_envelopes(tmp_path: Path) -> None:
    test_client, stubs = client(tmp_path)
    with test_client:
        for code, expected_status in (
            (AnalysisApplicationErrorCode.NOT_FOUND, 404),
            (AnalysisApplicationErrorCode.ARTIFACT_NOT_READY, 409),
            (AnalysisApplicationErrorCode.IDEMPOTENCY_CONFLICT, 409),
            (AnalysisApplicationErrorCode.SERVICE_UNAVAILABLE, 503),
        ):
            stubs["get"].error = AnalysisApplicationError(code)
            response = test_client.get(f"/api/analyses/{ANALYSIS_ID}")
            assert response.status_code == expected_status
            assert response.headers["content-type"].startswith("application/json")
            assert response.json()["code"] == code.value
            assert set(response.json()) == {"code", "message", "data"}


def test_retired_skill_entries_cannot_create_or_retry_but_history_remains(tmp_path):
    test_client, stubs = client(tmp_path)
    with test_client:
        assert test_client.get("/api/skills?input_kind=video").status_code == 404
        for path in (
            "/api/analyses",
            "/api/creation/projects",
            "/api/content/analyses",
        ):
            assert (
                test_client.post(
                    path, headers={"Idempotency-Key": "retired"}, json={}
                ).status_code
                == 404
            )
        assert test_client.get(f"/api/analyses/{ANALYSIS_ID}").status_code == 200
        assert (
            test_client.get(f"/api/downloads/{DOWNLOAD_ID}/analysis").status_code == 200
        )
        assert (
            test_client.get(f"/api/documents/{DOCUMENT_ID}/analysis").json()["data"]
            is None
        )
        assert (
            test_client.post(f"/api/analyses/{ANALYSIS_ID}/cancel").status_code == 200
        )
        assert test_client.delete(f"/api/analyses/{ANALYSIS_ID}").status_code == 204
    owners = (
        stubs["get"].calls[0][1],
        stubs["cancel"].calls[0][1],
        stubs["delete"].calls[0][1],
    )
    assert set(owners) == {TEST_USER.owner_hash}
