from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.main import create_app


def test_download_openapi_exposes_required_routes_and_idempotency(
    tmp_path: Path,
) -> None:
    app = create_app(Settings(app_env="test"))
    schema = app.openapi()
    paths = schema["paths"]

    assert {
        "/api/inspections",
        "/api/inspections/{inspection_id}",
        "/api/downloads",
        "/api/downloads/{job_id}",
        "/api/downloads/{job_id}/cancel",
        "/api/downloads/{job_id}/retry",
        "/api/downloads/{job_id}/download-url",
        "/api/downloads/{job_id}/file",
        "/api/admin/downloads/analytics",
        "/api/providers",
    } <= paths.keys()
    for path in (
        "/api/inspections",
        "/api/downloads",
        "/api/downloads/{job_id}/retry",
    ):
        parameters = paths[path]["post"]["parameters"]
        header = next(item for item in parameters if item["name"] == "Idempotency-Key")
        assert header["in"] == "header"
        assert header["required"] is True
    assert paths["/api/inspections"]["post"]["operationId"] == "inspectMedia"
    assert paths["/api/downloads"]["post"]["operationId"] == "createDownload"
    assert paths["/api/downloads/{job_id}"]["delete"]["operationId"] == "deleteDownload"
    assert "204" in paths["/api/downloads/{job_id}"]["delete"]["responses"]
    assert (
        paths["/api/downloads/{job_id}/retry"]["post"]["operationId"] == "retryDownload"
    )
    assert (
        paths["/api/downloads/{job_id}/file"]["head"]["operationId"]
        == "inspectDownloadFile"
    )
    assert paths["/api/providers"]["get"]["operationId"] == "listProviders"
    assert not any("authorization" in path for path in paths if "providers" in path)
    download_url = paths["/api/downloads/{job_id}/download-url"]["post"]
    preview = next(
        item for item in download_url["parameters"] if item["name"] == "preview"
    )
    assert preview["in"] == "query"
    assert preview["required"] is False
    assert preview["schema"]["default"] is False
    create_response = paths["/api/downloads"]["post"]["responses"]["201"]
    assert create_response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ApiResponse_DownloadResponse_"
    }
    download_fields = schema["components"]["schemas"]["DownloadResponse"]["properties"]
    presentation_fields = {
        "title",
        "thumbnail_url",
        "duration_seconds",
        "extractor_key",
        "format",
    }
    assert presentation_fields <= download_fields.keys()
    assert {"source_kind", "source_label"} <= download_fields.keys()
    assert schema["components"]["schemas"]["DownloadSourceKind"]["enum"] == [
        "remote_provider",
        "browser_import",
    ]
    assert all(
        sensitive not in download_fields
        for sensitive in ("object_key", "provider_hints", "url")
    )


def test_admin_download_analytics_openapi_is_bounded_and_safe(
    tmp_path: Path,
) -> None:
    app = create_app(Settings(app_env="test"))
    schema = app.openapi()
    operation = schema["paths"]["/api/admin/downloads/analytics"]["get"]

    assert operation["operationId"] == "getDownloadAnalytics"
    days = next(item for item in operation["parameters"] if item["name"] == "days")
    assert days["required"] is False
    assert days["schema"]["minimum"] == 7
    assert days["schema"]["maximum"] == 365
    assert days["schema"]["default"] == 30
    response = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response == {
        "$ref": "#/components/schemas/ApiResponse_DownloadAnalyticsResponse_"
    }
    components = schema["components"]["schemas"]
    analytics_contract = "".join(
        str(components[name])
        for name in (
            "DownloadAnalyticsResponse",
            "DownloadAnalyticsSummaryResponse",
            "DownloadAnalyticsDailyResponse",
            "DownloadAnalyticsSourceResponse",
        )
    )
    assert all(
        sensitive not in analytics_contract
        for sensitive in ("owner_hash", "url", "provider_hints", "error_message")
    )
    success_rate = components["DownloadAnalyticsSummaryResponse"]["properties"][
        "success_rate"
    ]
    assert success_rate["minimum"] == 0
    assert success_rate["maximum"] == 100


def test_request_schemas_forbid_unknown_fields_and_plan_has_no_hints(
    tmp_path: Path,
) -> None:
    app = create_app(Settings(app_env="test"))
    components = app.openapi()["components"]["schemas"]

    assert components["InspectionRequest"]["additionalProperties"] is False
    assert components["DownloadRequest"]["additionalProperties"] is False
    plan_properties = components["SemanticPlanResponse"]["properties"]
    assert "hints" not in plan_properties
    assert "provider_hints" not in plan_properties
    history_fields = components["DownloadHistoryItemResponse"]["properties"]
    assert {"source_kind", "source_label"} <= history_fields.keys()


def test_provider_status_contract_is_coarse_and_non_secret(tmp_path: Path) -> None:
    app = create_app(Settings(app_env="test"))
    components = app.openapi()["components"]["schemas"]
    contract = str(components["ProviderStatusResponse"])

    assert all(
        field in contract
        for field in (
            "registered",
            "extractor_exists",
            "capabilities",
            "identity",
            "status",
            "download_supported",
        )
    )
    assert all(
        sensitive not in contract
        for sensitive in (
            "cookie",
            "credential_version",
            "egress_affinity",
            "canary_url",
            "po_token",
        )
    )


def test_thumbnail_responses_declare_binary_content_for_generated_clients() -> None:
    paths = create_app(Settings(app_env="test")).openapi()["paths"]
    for path in (
        "/api/inspections/{inspection_id}/thumbnail",
        "/api/downloads/{job_id}/thumbnail",
    ):
        content = paths[path]["get"]["responses"]["200"]["content"]
        for media_type in ("image/avif", "image/jpeg", "image/png", "image/webp"):
            assert content[media_type]["schema"] == {
                "type": "string",
                "format": "binary",
            }
