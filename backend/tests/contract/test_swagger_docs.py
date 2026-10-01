from pathlib import Path

from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_swagger_ui_and_openapi_contract_are_available(tmp_path: Path) -> None:
    app = create_app(Settings(app_env="test"))

    with TestClient(app) as client:
        docs = client.get("/docs")
        schema_response = client.get("/openapi.json")

    assert docs.status_code == 200
    assert "Swagger UI" in docs.text
    assert schema_response.status_code == 200

    schema = schema_response.json()
    assert schema["info"]["title"] == "视频下载与分析服务 API"
    assert {tag["name"] for tag in schema["tags"]} == {
        "system",
        "auth",
        "users",
        "admin",
        "inspections",
        "download-intents",
        "source-discoveries",
        "media-imports",
        "providers",
        "downloads",
        "analyses",
    }
    assert all(not path.startswith("/api/v1") for path in schema["paths"])

    http_methods = {
        "delete",
        "get",
        "head",
        "options",
        "patch",
        "post",
        "put",
        "trace",
    }
    operation_list = [
        operation
        for path_item in schema["paths"].values()
        for method, operation in path_item.items()
        if method in http_methods
    ]
    operation_ids = [operation.get("operationId") for operation in operation_list]
    assert all(
        isinstance(operation_id, str) and operation_id for operation_id in operation_ids
    )
    assert len(operation_ids) == len(set(operation_ids))
    operations = dict(zip(operation_ids, operation_list, strict=True))
    assert set(operations) == {
        "getLiveness",
        "getReadiness",
        "registerNativeUser",
        "sendNativeRegistrationCode",
        "verifyNativeRegistrationCode",
        "sendRegistrationCode",
        "verifyRegistrationCode",
        "loginNativeUser",
        "getNativeCurrentUser",
        "refreshNativeSession",
        "logoutNativeSession",
        "registerUser",
        "loginUser",
        "getCurrentUser",
        "logoutUser",
        "updateCurrentUser",
        "getCurrentUserAvatar",
        "uploadCurrentUserAvatar",
        "deleteCurrentUserAvatar",
        "listUsers",
        "deleteUser",
        "updateUserAccess",
        "getDownloadAnalytics",
        "listStoredFiles",
        "deleteStoredFile",
        "cleanupStoredFiles",
        "listAiProviderProfiles",
        "listOpenRouterModels",
        "createAiProviderProfile",
        "updateAiProviderProfile",
        "activateAiProviderProfile",
        "deleteAiProviderProfile",
        "listProviderCatalogEntries",
        "getAdminEngineCatalog",
        "createProviderCatalogEntry",
        "updateProviderCatalogEntry",
        "deleteProviderCatalogEntry",
        "createSourceDiscovery",
        "getSourceDiscovery",
        "inspectMedia",
        "createDownloadIntent",
        "findDownloadIntent",
        "listDownloadIntents",
        "listHistoryRecords",
        "listOperationLogs",
        "getAnalysisHistoryRecord",
        "listAnalysisRuns",
        "refreshDownloadIntent",
        "getDownloadIntent",
        "cancelDownloadIntent",
        "getInspection",
        "getInspectionThumbnail",
        "listProviders",
        "createDownload",
        "deleteDownload",
        "createMediaImport",
        "getMediaImport",
        "createMediaUploadSession",
        "completeMediaImport",
        "createDocumentImport",
        "getDocumentImport",
        "listDocuments",
        "createDocumentUploadSession",
        "completeDocumentImport",
        "cancelDocumentImport",
        "deleteDocument",
        "getDownload",
        "inspectDownloadFile",
        "downloadFile",
        "getDownloadHistory",
        "getDownloadThumbnail",
        "cancelDownload",
        "retryDownload",
        "issueDownloadUrl",
        "listAnalysisSkills",
        "createAnalysis",
        "createDocumentAnalysis",
        "getAnalysis",
        "getLatestDownloadAnalysis",
        "getLatestDocumentAnalysis",
        "exportAnalysisMarkdown",
        "exportAnalysisReport",
        "cancelAnalysis",
        "retryAnalysis",
        "deleteAnalysis",
    }
    assert all(len(operation["tags"]) == 1 for operation in operations.values())

    components = schema["components"]["schemas"]
    assert components["ProviderIdentity"]["enum"] == ["none", "prefer", "required"]
    assert components["LivenessResponse"]["properties"]["status"]["$ref"] == (
        "#/components/schemas/LivenessStatus"
    )
    assert components["LivenessStatus"]["enum"] == ["ok"]
    assert components["ReadinessResponse"]["properties"]["status"]["$ref"] == (
        "#/components/schemas/ReadinessStatus"
    )
    assert components["ReadinessStatus"]["enum"] == ["ok", "unavailable"]

    validation_response = schema["paths"]["/api/downloads"]["post"]["responses"]["422"]
    assert validation_response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
