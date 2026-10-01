"""Analysis persistence composed from explicit transaction capabilities."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.analysis.analytics_repository import AnalysisAnalyticsRepository
from app.repositories.analysis.repository_base import AnalysisRepositoryBase
from app.repositories.analysis.repository_create import AnalysisCreationRepository
from app.repositories.analysis.repository_inputs import AnalysisInputRepository
from app.repositories.analysis.repository_lifecycle import AnalysisLifecycleRepository
from app.repositories.analysis.repository_publish import AnalysisPublishRepository
from app.repositories.analysis.repository_recovery import AnalysisRecoveryRepository
from app.repositories.analysis.repository_retry import AnalysisRetryRepository
from app.repositories.analysis.step_journal import AnalysisStepJournalRepository
from app.services.quotas import QuotaPolicy


class SqlAlchemyAnalysisRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        quota_policy: QuotaPolicy | None = None,
    ) -> None:
        reads = AnalysisRepositoryBase(sessions, quota_policy=quota_policy)
        self.get_job = reads.get_job
        self.get_result = reads.get_result
        self.get_latest_report = reads.get_latest_report
        self.get_current_report_file = reads.get_current_report_file
        analytics = AnalysisAnalyticsRepository(sessions, quota_policy=quota_policy)
        self.get_analysis_analytics = analytics.get_analysis_analytics
        creation = AnalysisCreationRepository(sessions, quota_policy=quota_policy)
        self.create_job_and_enqueue = creation.create_job_and_enqueue
        inputs = AnalysisInputRepository(sessions, quota_policy=quota_policy)
        self.get_artifact_for_download = inputs.get_artifact_for_download
        self.get_artifact = inputs.get_artifact
        self.get_document_for_analysis = inputs.get_document_for_analysis
        self.get_screenplay_source = inputs.get_screenplay_source
        lifecycle = AnalysisLifecycleRepository(sessions, quota_policy=quota_policy)
        self.get_latest_job_for_download = lifecycle.get_latest_job_for_download
        self.get_latest_job_for_document = lifecycle.get_latest_job_for_document
        self.delete_job = lifecycle.delete_job
        self.claim_run = lifecycle.claim_run
        self.heartbeat = lifecycle.heartbeat
        self.cancel_job = lifecycle.cancel_job
        publication = AnalysisPublishRepository(sessions, quota_policy=quota_policy)
        self.publish_result = publication.publish_result
        recovery = AnalysisRecoveryRepository(sessions, quota_policy=quota_policy)
        self.complete_failure = recovery.complete_failure
        self.fail_run = recovery.fail_run
        steps = AnalysisStepJournalRepository(sessions)
        self.begin_step = steps.begin_step
        self.complete_step = steps.complete_step
        self.abandon_step = steps.abandon_step
        self.has_started_step = steps.has_started_step
        self.purge_steps = steps.purge_steps
        retry = AnalysisRetryRepository(sessions, quota_policy=quota_policy)
        self.retry_job_and_enqueue = retry.retry_job_and_enqueue
