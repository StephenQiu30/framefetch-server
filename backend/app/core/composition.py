"""Composition root for the API process."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.core.runtime import (
    AnalysisUseCases,
    ApiRuntime,
    ApiServices,
    DocumentImportUseCases,
    DownloadUseCases,
    MediaImportUseCases,
    SourceDiscoveryUseCases,
)
from app.core.security.ai_provider_cipher import FernetAiProviderSecretCipher
from app.core.security.url_cipher import URLCipher
from app.integrations.ai_api.catalog import OpenRouterModelCatalog
from app.integrations.analysis_skill_catalog import BuiltinAnalysisSkillCatalog
from app.integrations.article_discovery.adapter import WeChatArticleDiscoveryAdapter
from app.integrations.jwt_tokens import JwtTokenService
from app.integrations.media_runner_factory import session_media_runner
from app.integrations.object_storage import MinioObjectStorage
from app.integrations.passwords import Argon2PasswordHasher
from app.integrations.provider_status import configured_provider_statuses
from app.integrations.rate_limiter import RedisRateLimiter
from app.integrations.readiness import build_runtime_readiness
from app.integrations.realtime import RabbitMqRealtimeConsumer, RealtimeHub
from app.integrations.registration_mail import SmtpRegistrationMailer
from app.integrations.thumbnail_storage import MinioThumbnailStorage
from app.integrations.url_security import FernetUrlEnvelope, MediaUrlValidator
from app.repositories.ai_provider_repository import SqlAlchemyAiProviderRepository
from app.repositories.analysis.repository import SqlAlchemyAnalysisRepository
from app.repositories.analysis.worker_registry import (
    ANALYSIS_MESSAGE_SCHEMA_VERSION,
    SqlAlchemyAnalysisWorkerRegistry,
)
from app.repositories.auth.auth_repository import SqlAlchemyAuthRepository
from app.repositories.auth.email_verification_repository import (
    SqlAlchemyVerificationStore,
)
from app.repositories.auth.redis_auth_repository import (
    RedisAuthRepository,
    RedisAuthSessionStore,
)
from app.repositories.auth.user_repository import SqlAlchemyUserRepository
from app.repositories.auth.web_sessions import WebSessionRepository
from app.repositories.documents.catalog_repository import (
    SqlAlchemyDocumentCatalogRepository,
)
from app.repositories.documents.delete_repository import (
    SqlAlchemyDocumentDeleteRepository,
)
from app.repositories.documents.import_repository import (
    SqlAlchemyDocumentImportRepository,
)
from app.repositories.downloads.intent_repository import IntentRepository
from app.repositories.downloads.repository import SqlAlchemyDownloadRepository
from app.repositories.history_records import SqlAlchemyHistoryRecordRepository
from app.repositories.imports.repository import SqlAlchemyMediaImportRepository
from app.repositories.operation_logs import OperationLogStore
from app.repositories.operational_metrics import OperationalMetrics
from app.repositories.providers.catalog_repository import (
    SqlAlchemyProviderCatalogRepository,
)
from app.repositories.source_discoveries.repository import (
    SqlAlchemySourceDiscoveryRepository,
)
from app.repositories.storage_files.repository import SqlAlchemyStorageFileRepository
from app.repositories.task_event_store import TaskEventStore
from app.services.ai_providers import AiProviderService
from app.services.analysis.analytics import GetAnalysisAnalytics
from app.services.analysis.cancel_analysis import CancelAnalysis
from app.services.analysis.content_versions import ListContentVersions
from app.services.analysis.create_analysis import CreateAnalysis
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
from app.services.analysis.retry_analysis import RetryAnalysis
from app.services.auth.email_verification import EmailVerification
from app.services.auth.service import AuthService
from app.services.auth.user_service import UserService
from app.services.auth.web_sessions import WebSessionService
from app.services.documents.service import DeleteDocument, GetDocument, ListDocuments
from app.services.downloads.analytics import GetDownloadAnalytics
from app.services.downloads.create_download import CreateDownload
from app.services.downloads.delete_download import DeleteDownload
from app.services.downloads.fingerprints import HmacRequestFingerprinter
from app.services.downloads.history import GetDownloadHistory
from app.services.downloads.inspect_media import InspectMedia
from app.services.downloads.intents import IntentService
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
    PersistThumbnail,
)
from app.services.history_records import HistoryRecordService
from app.services.imports.models import UploadLimits
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
from app.workers.runner.provider_registry import (
    configure_provider_instances,
)


def build_api_runtime(settings: Settings) -> ApiRuntime:
    if not settings.redis_url:
        raise ValueError("API auth sessions require REDIS_URL")
    configure_provider_instances(settings.peertube_allowed_instances)
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    realtime_hub = RealtimeHub(
        max_connections=settings.websocket_max_connections,
        max_per_owner=settings.websocket_max_connections_per_owner,
    )
    quota_policy = settings.quota_limits.policy(
        download_bytes=settings.max_file_size_bytes,
        document_normalized_bytes=settings.document_normalized_max_characters * 4,
        report_bytes=settings.analysis_report_max_bytes,
        thumbnail_bytes=settings.download_thumbnail_max_bytes,
    )
    repository = SqlAlchemyDownloadRepository(sessions, quota_policy=quota_policy)
    source_discovery_repository = SqlAlchemySourceDiscoveryRepository(sessions)
    media_import_repository = SqlAlchemyMediaImportRepository(
        sessions, quota_policy=quota_policy
    )
    document_import_repository = SqlAlchemyDocumentImportRepository(
        sessions, quota_policy=quota_policy
    )
    document_catalog_repository = SqlAlchemyDocumentCatalogRepository(sessions)
    document_delete_repository = SqlAlchemyDocumentDeleteRepository(sessions)
    analysis_repository = SqlAlchemyAnalysisRepository(
        sessions, quota_policy=quota_policy
    )
    analysis_availability = SqlAlchemyAnalysisWorkerRegistry(
        sessions,
        expected_app_version=settings.app_version,
        expected_message_schema_version=ANALYSIS_MESSAGE_SCHEMA_VERSION,
        stale_after=timedelta(seconds=settings.analysis_worker_stale_seconds),
    )
    auth_database_repository = SqlAlchemyAuthRepository(sessions)
    auth_session_store = RedisAuthSessionStore(settings.redis_url)
    auth_repository = RedisAuthRepository(
        auth_database_repository,
        auth_session_store,
    )
    user_repository = SqlAlchemyUserRepository(
        sessions,
        revoke_sessions=auth_session_store.delete_user_sessions,
    )
    provider_catalog_repository = SqlAlchemyProviderCatalogRepository(sessions)
    ai_provider_repository = SqlAlchemyAiProviderRepository(sessions)
    store = repository
    runner = session_media_runner(settings)
    storage = MinioObjectStorage(settings, enable_public_signing=True)
    thumbnail_storage = MinioThumbnailStorage(storage)
    persist_thumbnail = PersistThumbnail(store, thumbnail_storage)
    rate_limiter = (
        RedisRateLimiter(
            settings.redis_url,
            settings.request_fingerprint_secret.get_secret_value().encode(),
            policies=settings.rate_limit_policies,
        )
        if settings.redis_url
        else None
    )
    clock = _utc_now
    auth_service = AuthService(
        repository=auth_repository,
        verification=EmailVerification(
            SqlAlchemyVerificationStore(sessions),
            SmtpRegistrationMailer(settings),
            settings.auth_jwt_secret.get_secret_value().encode(),
            clock,
        ),
        passwords=Argon2PasswordHasher(),
        tokens=JwtTokenService(
            secret=settings.auth_jwt_secret.get_secret_value().encode(),
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            access_ttl=timedelta(seconds=settings.auth_access_token_ttl_seconds),
            refresh_ttl=timedelta(seconds=settings.auth_refresh_token_ttl_seconds),
        ),
        now=clock,
        new_id=uuid4,
        bootstrap_admin_email=(
            str(settings.auth_bootstrap_admin_email)
            if settings.auth_bootstrap_admin_email is not None
            else None
        ),
        bootstrap_admin_secret=settings.auth_bootstrap_admin_secret.get_secret_value(),
    )
    user_service = UserService(repository=user_repository, now=clock)
    provider_baselines = configured_provider_statuses()
    provider_catalog_service = ProviderCatalogService(
        provider_catalog_repository,
        provider_baselines,
        now=clock,
    )
    ai_provider_service = AiProviderService(
        ai_provider_repository,
        FernetAiProviderSecretCipher(
            URLCipher(settings.url_encryption_key.get_secret_value().encode()),
            key_id=settings.url_encryption_key_id,
        ),
        now=clock,
        availability=analysis_availability,
        model_catalog=OpenRouterModelCatalog(),
    )
    storage_file_service = StorageFileService(
        SqlAlchemyStorageFileRepository(sessions),
        storage.delete,
        now=clock,
    )
    fingerprinter = HmacRequestFingerprinter(
        settings.request_fingerprint_secret.get_secret_value().encode()
    )
    envelope = FernetUrlEnvelope(
        URLCipher(settings.url_encryption_key.get_secret_value().encode()),
        key_id=settings.url_encryption_key_id,
    )
    inspect_media = InspectMedia(
        repository=store,
        runner=runner,
        url_validator=MediaUrlValidator(),
        url_cipher=envelope,
        fingerprinter=fingerprinter,
        now=clock,
        new_id=uuid4,
        inspection_ttl=timedelta(seconds=settings.inspection_ttl_seconds),
        max_duration_seconds=settings.max_video_duration_seconds,
        persist_thumbnail=persist_thumbnail,
    )
    inspect_discovered_item = InspectDiscoveredItem(
        source_discovery_repository,
        store,
        fingerprinter,
        now=clock,
        new_id=uuid4,
        inspection_ttl=timedelta(seconds=settings.inspection_ttl_seconds),
    )
    source_discovery_use_cases = SourceDiscoveryUseCases(
        create=CreateSourceDiscovery(
            source_discovery_repository,
            WeChatArticleDiscoveryAdapter(
                timeout_seconds=settings.article_discovery_timeout_seconds,
                max_response_bytes=settings.article_discovery_max_response_bytes,
                max_items=settings.article_discovery_max_items,
                min_interval_seconds=(settings.article_discovery_min_interval_seconds),
                proxy_url=settings.article_discovery_proxy_url,
            ),
            envelope,
            fingerprinter,
            now=clock,
            new_id=uuid4,
            ttl=timedelta(seconds=settings.article_discovery_ttl_seconds),
            max_items=settings.article_discovery_max_items,
        ),
        get=GetSourceDiscovery(source_discovery_repository, now=clock),
    )
    upload_limits = UploadLimits(
        part_size_bytes=settings.import_upload_part_size_bytes,
        max_parts=settings.import_upload_max_parts,
        max_concurrency=settings.import_upload_max_concurrency,
        session_ttl=timedelta(seconds=settings.import_upload_session_ttl_seconds),
    )
    cancel_import = CancelImport(
        media_import_repository,
        storage,
        now=clock,
    )
    media_import_use_cases = MediaImportUseCases(
        create_resource=CreateImportResource(
            repository=media_import_repository,
            fingerprinter=fingerprinter,
            now=clock,
            new_id=uuid4,
            media_enabled=settings.media_import_enabled,
            document_enabled=False,
            media_max_bytes=settings.media_import_max_bytes,
            document_max_bytes=settings.document_import_max_bytes,
            rights_statement_version=settings.import_rights_statement_version,
        ),
        create_upload_session=CreateUploadSession(
            media_import_repository,
            storage,
            now=clock,
            limits=upload_limits,
        ),
        complete_upload=CompleteImportUpload(
            media_import_repository,
            storage,
            now=clock,
        ),
        get_import=GetImport(
            media_import_repository,
            storage,
            now=clock,
        ),
        cancel_import=cancel_import,
    )
    document_import_use_cases = DocumentImportUseCases(
        create_resource=CreateImportResource(
            repository=document_import_repository,
            fingerprinter=fingerprinter,
            now=clock,
            new_id=uuid4,
            media_enabled=False,
            document_enabled=settings.document_import_enabled,
            media_max_bytes=settings.media_import_max_bytes,
            document_max_bytes=settings.document_import_max_bytes,
            rights_statement_version=settings.import_rights_statement_version,
        ),
        create_upload_session=CreateUploadSession(
            document_import_repository,
            storage,
            now=clock,
            limits=upload_limits,
        ),
        complete_upload=CompleteImportUpload(
            document_import_repository,
            storage,
            now=clock,
        ),
        get_import=GetImport(
            document_import_repository,
            storage,
            now=clock,
        ),
        cancel_import=CancelImport(
            document_import_repository,
            storage,
            now=clock,
        ),
        get_document=GetDocument(
            document_catalog_repository,
            storage,
            max_preview_bytes=settings.document_preview_max_bytes,
            max_preview_characters=settings.document_preview_max_characters,
        ),
        list_documents=ListDocuments(document_catalog_repository),
        delete_document=DeleteDocument(
            document_delete_repository,
            storage,
            now=clock,
        ),
    )
    cancel_download = CancelDownload(
        store,
        now=clock,
        browser_import_canceller=cancel_import,
    )
    use_cases = DownloadUseCases(
        inspect_media=inspect_media,
        inspect_discovered_item=inspect_discovered_item,
        get_inspection=GetInspection(store, now=clock),
        get_thumbnail=GetThumbnail(store, thumbnail_storage, persist_thumbnail),
        get_download_thumbnail=GetDownloadThumbnail(store, thumbnail_storage),
        create_download=CreateDownload(
            repository=store,
            fingerprinter=fingerprinter,
            now=clock,
            new_id=uuid4,
            max_attempts=settings.max_download_attempts,
        ),
        delete_download=DeleteDownload(
            store,
            storage,
            cancel_download,
            now=clock,
        ),
        get_download=GetDownload(store, now=clock),
        get_download_artifact=GetDownloadArtifact(store, now=clock),
        get_download_history=GetDownloadHistory(store, now=clock),
        get_download_analytics=GetDownloadAnalytics(store, now=clock),
        cancel_download=cancel_download,
        retry_download=RetryDownload(
            repository=store,
            fingerprinter=fingerprinter,
            now=clock,
            new_id=uuid4,
            max_attempts=settings.max_download_attempts,
        ),
        issue_download_url=IssueDownloadUrl(
            store,
            storage,
            now=clock,
            url_ttl=timedelta(seconds=settings.artifact_download_url_ttl_seconds),
        ),
    )
    get_analysis = GetAnalysis(analysis_repository)
    skill_catalog = BuiltinAnalysisSkillCatalog()
    analysis_use_cases = AnalysisUseCases(
        list_analysis_skills=skill_catalog.list,
        create_analysis=CreateAnalysis(
            repository=analysis_repository,
            fingerprinter=fingerprinter,
            now=clock,
            new_id=uuid4,
            max_attempts=1,
            skill_catalog=skill_catalog,
            enabled=settings.analysis_enabled,
        ),
        create_document_analysis=CreateDocumentAnalysis(
            repository=analysis_repository,
            fingerprinter=fingerprinter,
            now=clock,
            new_id=uuid4,
            max_attempts=1,
            skill_catalog=skill_catalog,
            enabled=settings.analysis_enabled and settings.screenplay_analysis_enabled,
            max_source_characters=settings.analysis_screenplay_single_call_characters,
        ),
        retry_analysis=RetryAnalysis(
            analysis_repository,
            now=clock,
            new_id=uuid4,
            skill_catalog=skill_catalog,
            max_runs_per_job=settings.analysis_max_runs_per_job,
            min_interval_seconds=settings.analysis_manual_retry_min_interval_seconds,
            retries_per_day=settings.analysis_manual_retries_per_day,
        ),
        get_content_source=GetContentSource(analysis_repository),
        list_content_versions=ListContentVersions(analysis_repository),
        get_analysis_analytics=GetAnalysisAnalytics(analysis_repository, now=clock),
        delete_analysis=DeleteAnalysis(analysis_repository, now=clock),
        get_analysis=get_analysis,
        get_latest_download_analysis=GetLatestDownloadAnalysis(
            analysis_repository, get_analysis
        ),
        get_latest_document_analysis=GetLatestDocumentAnalysis(
            analysis_repository, get_analysis
        ),
        cancel_analysis=CancelAnalysis(analysis_repository, now=clock),
        export_analysis_report=ExportAnalysisReport(
            get_analysis, analysis_repository, storage
        ),
        export_analysis_markdown=ExportAnalysisMarkdown(
            get_analysis, analysis_repository, storage
        ),
    )

    return ApiRuntime(
        services=ApiServices(
            engine_catalog_reader=runner.engine_catalog,
            intent_service=IntentService(
                IntentRepository(sessions, quota_policy=quota_policy),
                MediaUrlValidator(),
                envelope,
                fingerprinter,
                now=clock,
                new_id=uuid4,
            ),
            history_record_service=HistoryRecordService(
                SqlAlchemyHistoryRecordRepository(sessions), envelope, fingerprinter
            ),
            auth_service=auth_service,
            web_session_service=WebSessionService(
                WebSessionRepository(sessions),
                now=clock,
                idle_ttl=timedelta(seconds=settings.auth_web_idle_ttl_seconds),
                absolute_ttl=timedelta(seconds=settings.auth_web_absolute_ttl_seconds),
            ),
            user_service=user_service,
            download_use_cases=use_cases,
            analysis_use_cases=analysis_use_cases,
            media_import_use_cases=media_import_use_cases,
            document_import_use_cases=document_import_use_cases,
            source_discovery_use_cases=source_discovery_use_cases,
            rate_limiter=rate_limiter,
            readiness_probe=build_runtime_readiness(
                settings,
                engine,
                redis_check=rate_limiter.ping if rate_limiter is not None else None,
            ),
            realtime_hub=realtime_hub,
            task_event_store=TaskEventStore(sessions),
            operation_log_store=OperationLogStore(sessions),
            operational_metrics=OperationalMetrics(sessions),
            provider_status_service=ProviderStatusService(
                provider_baselines,
                catalog=provider_catalog_repository,
            ),
            provider_catalog_service=provider_catalog_service,
            ai_provider_service=ai_provider_service,
            storage_file_service=storage_file_service,
            download_storage=storage,
        ),
        engine=engine,
        runner=runner,
        auth_session_store=auth_session_store,
        realtime_consumer=RabbitMqRealtimeConsumer(
            settings.rabbitmq_url,
            settings.rabbitmq_exchange,
            realtime_hub,
            connection_timeout=settings.rabbitmq_connection_timeout_seconds,
            heartbeat=settings.rabbitmq_heartbeat_seconds,
            reconnect_interval=settings.rabbitmq_reconnect_interval_seconds,
        ),
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)
