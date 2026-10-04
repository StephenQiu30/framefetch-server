"""Typed services and resources shared by the API lifespan."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from app.integrations.media_runner import MediaRunnerHttpClient
from app.integrations.rate_limiter import RedisRateLimiter
from app.integrations.readiness import (
    RuntimeReadiness,
    assert_download_execution_schema,
)
from app.integrations.realtime import RabbitMqRealtimeConsumer, RealtimeHub
from app.repositories.auth.redis_auth_repository import RedisAuthSessionStore
from app.repositories.operation_logs import OperationLogStore
from app.repositories.operational_metrics import OperationalMetrics
from app.repositories.task_event_store import TaskEventStore
from app.schemas.engine_catalog import EngineCatalogResponse
from app.services.ai_providers import AiProviderService
from app.services.analysis.analytics import GetAnalysisAnalytics
from app.services.analysis.cancel_analysis import CancelAnalysis
from app.services.analysis.content_revision import ReviseContent
from app.services.analysis.content_versions import ListContentVersions
from app.services.analysis.create_analysis import CreateAnalysis
from app.services.analysis.create_content_analysis import CreateContentAnalysis
from app.services.analysis.create_document_analysis import CreateDocumentAnalysis
from app.services.analysis.delete_analysis import DeleteAnalysis
from app.services.analysis.export_report import (
    ExportAnalysisMarkdown,
    ExportAnalysisReport,
)
from app.services.analysis.get_analysis import GetAnalysis
from app.services.analysis.get_content_source import GetContentSource
from app.services.analysis.get_latest_analysis import (
    GetLatestDocumentAnalysis,
    GetLatestDownloadAnalysis,
)
from app.services.analysis.models import AnalysisSkillView
from app.services.analysis.retry_analysis import RetryAnalysis
from app.services.analysis.rules.enums import AnalysisInputKind
from app.services.auth.service import AuthService
from app.services.auth.user_service import UserService
from app.services.auth.web_sessions import WebSessionService
from app.services.documents.service import DeleteDocument, GetDocument, ListDocuments
from app.services.downloads.analytics import GetDownloadAnalytics
from app.services.downloads.create_download import CreateDownload
from app.services.downloads.delete_download import DeleteDownload
from app.services.downloads.history import GetDownloadHistory
from app.services.downloads.inspect_media import InspectMedia
from app.services.downloads.intents import IntentService
from app.services.downloads.ports import DownloadArtifactStorage
from app.services.downloads.queries import (
    CancelDownload,
    GetDownload,
    GetDownloadArtifact,
    GetInspection,
    IssueDownloadUrl,
)
from app.services.downloads.retry_download import RetryDownload
from app.services.downloads.thumbnail_use_cases import (
    GetDownloadThumbnail,
    GetThumbnail,
)
from app.services.history_records import HistoryRecordService
from app.services.imports.service import (
    CancelImport,
    CompleteImportUpload,
    CreateImportResource,
    CreateUploadSession,
    GetImport,
)
from app.services.provider_catalog import ProviderCatalogService
from app.services.provider_status import ProviderStatusService
from app.services.source_discoveries.use_cases import (
    CreateSourceDiscovery,
    GetSourceDiscovery,
    InspectDiscoveredItem,
)
from app.services.storage_files.service import StorageFileService


@dataclass(frozen=True, slots=True)
class DownloadUseCases:
    inspect_media: InspectMedia
    inspect_discovered_item: InspectDiscoveredItem
    get_inspection: GetInspection
    get_thumbnail: GetThumbnail
    get_download_thumbnail: GetDownloadThumbnail
    create_download: CreateDownload
    delete_download: DeleteDownload
    get_download: GetDownload
    get_download_artifact: GetDownloadArtifact
    get_download_history: GetDownloadHistory
    get_download_analytics: GetDownloadAnalytics
    cancel_download: CancelDownload
    retry_download: RetryDownload
    issue_download_url: IssueDownloadUrl


@dataclass(frozen=True, slots=True)
class SourceDiscoveryUseCases:
    create: CreateSourceDiscovery
    get: GetSourceDiscovery


@dataclass(frozen=True, slots=True)
class AnalysisUseCases:
    get_analysis_analytics: GetAnalysisAnalytics
    list_analysis_skills: Callable[[AnalysisInputKind], tuple[AnalysisSkillView, ...]]
    create_analysis: CreateAnalysis
    create_document_analysis: CreateDocumentAnalysis
    delete_analysis: DeleteAnalysis
    get_analysis: GetAnalysis
    get_latest_download_analysis: GetLatestDownloadAnalysis
    get_latest_document_analysis: GetLatestDocumentAnalysis
    cancel_analysis: CancelAnalysis
    retry_analysis: RetryAnalysis
    export_analysis_report: ExportAnalysisReport
    export_analysis_markdown: ExportAnalysisMarkdown
    create_content_analysis: CreateContentAnalysis | None = None
    get_content_source: GetContentSource | None = None
    revise_content: ReviseContent | None = None
    list_content_versions: ListContentVersions | None = None


@dataclass(frozen=True, slots=True)
class MediaImportUseCases:
    create_resource: CreateImportResource
    create_upload_session: CreateUploadSession
    complete_upload: CompleteImportUpload
    get_import: GetImport
    cancel_import: CancelImport


@dataclass(frozen=True, slots=True)
class DocumentImportUseCases:
    create_resource: CreateImportResource
    create_upload_session: CreateUploadSession
    complete_upload: CompleteImportUpload
    get_import: GetImport
    cancel_import: CancelImport
    get_document: GetDocument
    list_documents: ListDocuments
    delete_document: DeleteDocument


@dataclass(slots=True)
class ApiServices:
    engine_catalog_reader: Callable[[], Awaitable[EngineCatalogResponse]] | None = None
    intent_service: IntentService | None = None
    history_record_service: HistoryRecordService | None = None
    auth_service: AuthService | None = None
    web_session_service: WebSessionService | None = None
    user_service: UserService | None = None
    download_use_cases: DownloadUseCases | None = None
    analysis_use_cases: AnalysisUseCases | None = None
    media_import_use_cases: MediaImportUseCases | None = None
    document_import_use_cases: DocumentImportUseCases | None = None
    source_discovery_use_cases: SourceDiscoveryUseCases | None = None
    rate_limiter: RedisRateLimiter | None = None
    readiness_probe: RuntimeReadiness | None = None
    realtime_hub: RealtimeHub | None = None
    task_event_store: TaskEventStore | None = None
    operation_log_store: OperationLogStore | None = None
    operational_metrics: OperationalMetrics | None = None
    provider_status_service: ProviderStatusService | None = None
    provider_catalog_service: ProviderCatalogService | None = None
    ai_provider_service: AiProviderService | None = None
    storage_file_service: StorageFileService | None = None
    download_storage: DownloadArtifactStorage | None = None


@dataclass(slots=True)
class ApiRuntime:
    services: ApiServices
    engine: AsyncEngine
    runner: MediaRunnerHttpClient
    auth_session_store: RedisAuthSessionStore
    realtime_consumer: RabbitMqRealtimeConsumer

    async def start(self) -> None:
        await assert_download_execution_schema(self.engine)
        await self.realtime_consumer.start()

    async def close(self) -> None:
        # Every owner releases its resource even if an earlier close fails.
        async with AsyncExitStack() as cleanup:
            cleanup.push_async_callback(self.engine.dispose)
            cleanup.push_async_callback(self.auth_session_store.close)
            cleanup.push_async_callback(self.runner.close)
            if self.services.rate_limiter is not None:
                cleanup.push_async_callback(self.services.rate_limiter.close)
            if self.services.readiness_probe is not None:
                cleanup.push_async_callback(self.services.readiness_probe.close)
            cleanup.push_async_callback(self.realtime_consumer.close)
