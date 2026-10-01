from app.core.config import Settings
from app.main import create_app


def test_admin_analysis_analytics_openapi_exposes_bounded_aggregate_contract() -> None:
    schema = create_app(Settings(app_env="test", _env_file=None)).openapi()
    endpoint = schema["paths"]["/api/admin/analyses/analytics"]["get"]

    assert endpoint["operationId"] == "getAnalysisAnalytics"
    assert "analysis_run" in endpoint["description"]
    assert "软删除" in endpoint["description"]
    period = next(item for item in endpoint["parameters"] if item["name"] == "days")
    assert period["schema"] == {
        "type": "integer",
        "minimum": 7,
        "maximum": 365,
        "default": 30,
        "title": "Days",
    }
    components = schema["components"]["schemas"]
    response = components["AnalysisAnalyticsResponse"]
    assert response["additionalProperties"] is False
    assert set(response["properties"]) == {
        "period_days",
        "start",
        "end",
        "summary",
        "daily",
        "inputs",
    }
    summary = components["AnalysisAnalyticsSummaryResponse"]["properties"]
    assert set(summary) == {
        "total",
        "succeeded",
        "failed",
        "cancelled",
        "active",
        "average_duration_seconds",
        "completed_duration_count",
    }
    assert {item["type"] for item in summary["average_duration_seconds"]["anyOf"]} == {
        "number",
        "null",
    }
    assert components["AnalysisAnalyticsInputResponse"]["properties"]["input_kind"] == {
        "$ref": "#/components/schemas/AnalysisInputKind"
    }
