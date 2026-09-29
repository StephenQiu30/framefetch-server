from pathlib import Path

from app.core.config import Settings
from app.main import create_app
from app.services.analysis.rules.enums import AnalysisReportStatus


def test_analysis_openapi_is_current_and_excludes_internal_fields(
    tmp_path: Path,
) -> None:
    schema = create_app(Settings(app_env="test")).openapi()
    paths = schema["paths"]
    create_path = "/api/downloads/{download_id}/analyses"
    create_document_path = "/api/documents/{document_id}/analyses"

    assert {
        create_path,
        create_document_path,
        "/api/documents/{document_id}/analysis",
        "/api/analyses/{analysis_id}",
        "/api/analyses/{analysis_id}/cancel",
        "/api/analyses/{analysis_id}/retry",
        "/api/analyses/{analysis_id}/report.docx",
    } <= paths.keys()
    assert paths[create_path]["post"]["operationId"] == "createAnalysis"
    assert (
        paths[create_document_path]["post"]["operationId"] == "createDocumentAnalysis"
    )
    assert (
        paths["/api/documents/{document_id}/analysis"]["get"]["operationId"]
        == "getLatestDocumentAnalysis"
    )
    create_response = paths[create_path]["post"]["responses"]["201"]
    assert create_response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ApiResponse_AnalysisResponse_"
    }
    header = next(
        item
        for item in paths[create_path]["post"]["parameters"]
        if item["name"] == "Idempotency-Key"
    )
    assert header["required"] is True
    retry = paths["/api/analyses/{analysis_id}/retry"]["post"]
    assert retry["operationId"] == "retryAnalysis"

    delete = paths["/api/analyses/{analysis_id}"]["delete"]
    assert delete["operationId"] == "deleteAnalysis"
    assert "204" in delete["responses"]
    assert retry["responses"]["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ApiResponse_AnalysisResponse_"
    }
    retry_header = next(
        item for item in retry["parameters"] if item["name"] == "Idempotency-Key"
    )
    assert retry_header["required"] is True
    assert "requestBody" not in retry
    components = schema["components"]["schemas"]
    assert components["AnalysisRequest"]["additionalProperties"] is False
    fields = components["AnalysisResponse"]["properties"]
    report_fields = components["AnalysisReportResponse"]["properties"]
    assert report_fields["status"]["$ref"] == (
        "#/components/schemas/AnalysisReportStatus"
    )
    assert components["AnalysisReportStatus"]["enum"] == [
        status.value for status in AnalysisReportStatus
    ]
    assert "report_markdown" in fields
    assert {"run_id", "run_no", "run_trigger", "version"} <= set(fields)
    assert {"input_kind", "result_contract"} <= set(fields)
    assert components["AnalysisInputKind"]["enum"] == ["video", "screenplay"]
    assert components["AnalysisResultContract"]["enum"] == [
        "video-visual-analysis",
        "video-article",
        "screenplay-analysis",
        "screenplay-rewrite",
        "structured-report",
    ]
    assert {"artifact_id", "schema_version", "transcript", "provider"}.isdisjoint(
        fields
    )
    result_union = next(item for item in fields["result"]["anyOf"] if "oneOf" in item)
    assert result_union["discriminator"] == {
        "propertyName": "kind",
        "mapping": {
            "screenplay_analysis": (
                "#/components/schemas/ScreenplayAnalysisResultResponse"
            ),
            "video_article": "#/components/schemas/VideoArticleResultResponse",
            "screenplay_rewrite": (
                "#/components/schemas/ScreenplayRewriteResultResponse"
            ),
            "video_visual_analysis": (
                "#/components/schemas/VideoAnalysisResultResponse"
            ),
            "structured_report": (
                "#/components/schemas/StructuredReportResultResponse"
            ),
        },
    }
    assert {item["$ref"] for item in result_union["oneOf"]} == {
        "#/components/schemas/VideoAnalysisResultResponse",
        "#/components/schemas/VideoArticleResultResponse",
        "#/components/schemas/ScreenplayAnalysisResultResponse",
        "#/components/schemas/ScreenplayRewriteResultResponse",
        "#/components/schemas/StructuredReportResultResponse",
    }
    result_fields = components["VideoAnalysisResultResponse"]["properties"]
    assert {
        "media",
        "shot_count",
        "shots",
        "scenes",
        "highlights",
        "assets",
        "production_advice",
    } <= set(result_fields)
    shot_fields = components["ShotResponse"]["properties"]
    assert {"narrative_function", "highlight_score"} <= set(shot_fields)
    scene_fields = components["VideoSceneResponse"]["properties"]
    assert {
        "location",
        "narrative_function",
        "visual_rules",
        "continuity_risks",
        "evidence_shot_ids",
    } <= set(scene_fields)
    assert {"provider", "model", "cli_version"}.isdisjoint(result_fields)
    rewrite_fields = components["ScreenplayRewriteResultResponse"]["properties"]
    assert {"chunks", "rewritten_text"}.isdisjoint(rewrite_fields)
    export = paths["/api/analyses/{analysis_id}/report.docx"]["get"]
    assert export["operationId"] == "exportAnalysisReport"
    assert (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        in export["responses"]["200"]["content"]
    )
