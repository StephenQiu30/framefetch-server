from dataclasses import replace
from uuid import uuid4

from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
)
from app.services.analysis.models import AnalysisReportFile
from app.services.analysis.rules.enums import AnalysisInputKind, AnalysisResultContract
from tests.integration.api.test_analysis_routes import (
    ANALYSIS_ID,
    TEST_USER,
    StubUseCase,
    analysis_view,
    client,
)
from tests.unit.workers.analysis.test_content_execution import draft, source


def test_content_routes_dispatch_owner_and_preserve_private_sources(tmp_path):
    test_client, _ = client(tmp_path)
    use_cases = test_client.app.state.services.analysis_use_cases
    view = replace(
        analysis_view(),
        skill_id="content-article",
        input_kind=AnalysisInputKind.CONTENT,
        result_contract=AnalysisResultContract.CONTENT_DOCUMENT,
    )
    create = StubUseCase(view)
    revise = StubUseCase(view)
    original = StubUseCase(source())
    versions = StubUseCase(())
    test_client.app.state.services.analysis_use_cases = replace(
        use_cases,
        create_content_analysis=create,
        revise_content=revise,
        get_content_source=original,
        list_content_versions=versions,
    )
    with test_client:
        response = test_client.post(
            "/api/content/analyses",
            headers={"Idempotency-Key": "content-1"},
            json={
                "source": source().model_dump(mode="json"),
                "output_language": "zh-CN",
            },
        )
        assert response.status_code == 201
        assert response.headers["location"] == f"/api/analyses/{ANALYSIS_ID}"
        assert response.json()["data"]["input_kind"] == "content"
        assert create.calls[0][2:] == (TEST_USER.owner_hash, "content-1")
        fetched = test_client.get(f"/api/content/analyses/{ANALYSIS_ID}/source")
        assert fetched.json()["data"] == source().model_dump(mode="json")
        assert fetched.headers["cache-control"] == "private, no-store"
        assert original.calls == [(ANALYSIS_ID, TEST_USER.owner_hash)]
        saved = test_client.post(
            f"/api/content/analyses/{ANALYSIS_ID}/revisions",
            headers={"Idempotency-Key": "edit-1"},
            json={"base_report_id": str(uuid4()), "draft": draft()},
        )
        assert saved.status_code == 201
        assert revise.calls[0][:2] == (ANALYSIS_ID, TEST_USER.owner_hash)
        assert revise.calls[0][-1] == "edit-1"
        listed = test_client.get(f"/api/content/analyses/{ANALYSIS_ID}/versions")
        assert listed.status_code == 200 and listed.json()["data"] == []
        assert listed.headers["cache-control"] == "private, no-store"
        assert versions.calls == [(ANALYSIS_ID, TEST_USER.owner_hash)]
        malformed = test_client.post(
            "/api/content/analyses",
            headers={"Idempotency-Key": "bad-1"},
            json={"source": {"brief": {}, "materials": []}, "output_language": "zh-CN"},
        )
        assert malformed.status_code == 422
        assert len(create.calls) == 1
        original.error = AnalysisApplicationError(
            AnalysisApplicationErrorCode.NOT_FOUND
        )
        assert (
            test_client.get(f"/api/content/analyses/{ANALYSIS_ID}/source").status_code
            == 404
        )


def test_content_html_is_an_owner_scoped_attachment(tmp_path):
    test_client, _ = client(tmp_path)
    export = StubUseCase(
        AnalysisReportFile(
            content=b"<!doctype html><p>Reader prose</p>",
            filename="article.html",
            media_type="text/html",
        )
    )
    test_client.app.state.services.analysis_use_cases = replace(
        test_client.app.state.services.analysis_use_cases,
        export_analysis_html=export,
    )
    with test_client:
        response = test_client.get(f"/api/content/analyses/{ANALYSIS_ID}/report.html")
        assert response.status_code == 200 and b"Reader prose" in response.content
        assert (
            response.headers["content-disposition"]
            == 'attachment; filename="article.html"'
        )
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert export.calls == [(ANALYSIS_ID, TEST_USER.owner_hash)]
        export.error = AnalysisApplicationError(AnalysisApplicationErrorCode.NOT_FOUND)
        assert (
            test_client.get(
                f"/api/content/analyses/{ANALYSIS_ID}/report.html"
            ).status_code
            == 404
        )
