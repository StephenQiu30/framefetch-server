from dataclasses import replace

from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
)
from tests.integration.api.test_analysis_routes import (
    ANALYSIS_ID,
    TEST_USER,
    StubUseCase,
    client,
)
from tests.unit.workers.analysis.content_history_fixtures import draft, source


def test_legacy_content_sources_and_versions_remain_owner_scoped(tmp_path):
    test_client, _ = client(tmp_path)
    use_cases = test_client.app.state.services.analysis_use_cases
    original = StubUseCase(source())
    versions = StubUseCase(())
    test_client.app.state.services.analysis_use_cases = replace(
        use_cases, get_content_source=original, list_content_versions=versions
    )
    with test_client:
        fetched = test_client.get(f"/api/content/analyses/{ANALYSIS_ID}/source")
        assert fetched.json()["data"] == source().model_dump(mode="json")
        assert fetched.headers["cache-control"] == "private, no-store"
        assert original.calls == [(ANALYSIS_ID, TEST_USER.owner_hash)]
        listed = test_client.get(f"/api/content/analyses/{ANALYSIS_ID}/versions")
        assert listed.status_code == 200 and listed.json()["data"] == []
        assert listed.headers["cache-control"] == "private, no-store"
        assert versions.calls == [(ANALYSIS_ID, TEST_USER.owner_hash)]
        assert (
            test_client.post(
                "/api/content/analyses", headers={"Idempotency-Key": "retired"}, json={}
            ).status_code
            == 404
        )
        original.error = AnalysisApplicationError(
            AnalysisApplicationErrorCode.NOT_FOUND
        )
        assert (
            test_client.get(f"/api/content/analyses/{ANALYSIS_ID}/source").status_code
            == 404
        )


def test_removed_html_export_is_not_routed(tmp_path):
    test_client, _ = client(tmp_path)
    with test_client:
        assert (
            test_client.get(
                f"/api/content/analyses/{ANALYSIS_ID}/report.html"
            ).status_code
            == 404
        )


def test_manual_revision_is_not_routed(tmp_path):
    test_client, _ = client(tmp_path)
    with test_client:
        assert (
            test_client.post(
                f"/api/content/analyses/{ANALYSIS_ID}/revisions",
                headers={"Idempotency-Key": "retired-edit"},
                json={"base_report_id": str(ANALYSIS_ID), "draft": draft()},
            ).status_code
            == 404
        )
