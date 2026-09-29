from __future__ import annotations

from enum import StrEnum


class AnalysisStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisInputKind(StrEnum):
    VIDEO = "video"
    SCREENPLAY = "screenplay"


class AnalysisResultContract(StrEnum):
    VIDEO_VISUAL_ANALYSIS = "video-visual-analysis"
    VIDEO_ARTICLE = "video-article"
    SCREENPLAY_ANALYSIS = "screenplay-analysis"
    SCREENPLAY_REWRITE = "screenplay-rewrite"
    STRUCTURED_REPORT = "structured-report"


class AnalysisResultKind(StrEnum):
    VIDEO_VISUAL_ANALYSIS = "video_visual_analysis"
    VIDEO_ARTICLE = "video_article"
    SCREENPLAY_ANALYSIS = "screenplay_analysis"
    SCREENPLAY_REWRITE = "screenplay_rewrite"
    STRUCTURED_REPORT = "structured_report"


class AnalysisStage(StrEnum):
    PREPARING = "preparing"
    ANALYZING = "analyzing"
    VALIDATING = "validating"
    PUBLISHING = "publishing"


class AnalysisReportStatus(StrEnum):
    VALIDATED = "validated"
    PUBLISHING = "publishing"
    AVAILABLE = "available"
    PUBLISH_FAILED = "publish_failed"
    DELETE_PENDING = "delete_pending"
    DELETED = "deleted"


class AnalysisReportArtifactStatus(StrEnum):
    AVAILABLE = "available"
    DELETE_PENDING = "delete_pending"
    DELETED = "deleted"
    FAILED = "failed"


class AnalysisErrorCode(StrEnum):
    CANCELLED = "cancelled"
    CLI_UNAVAILABLE = "analysis_cli_unavailable"
    CLI_UNSUPPORTED = "analysis_cli_unsupported"
    CLI_NOT_AUTHENTICATED = "analysis_cli_not_authenticated"
    SANDBOX_UNAVAILABLE = "analysis_sandbox_unavailable"
    MEDIA_INVALID = "analysis_media_invalid"
    PROVIDER_RATE_LIMITED = "analysis_provider_rate_limited"
    PROVIDER_USAGE_LIMITED = "analysis_provider_usage_limited"
    CLI_TIMEOUT = "analysis_cli_timeout"
    CLI_FAILED = "analysis_cli_failed"
    INVALID_MODEL_OUTPUT = "invalid_model_output"
    RESOURCE_LIMIT = "analysis_resource_limit"
    INPUT_ARTIFACT_UNAVAILABLE = "input_artifact_unavailable"
    INPUT_EXPIRED = "analysis_input_expired"
    SCREENPLAY_OUTPUT_INCOMPLETE = "screenplay_output_incomplete"
    REPORT_UNAVAILABLE = "analysis_report_unavailable"
    INTERNAL_ERROR = "internal_error"
    WORKER_LOST = "worker_lost"
    OUTCOME_UNKNOWN = "analysis_outcome_unknown"

    @property
    def retryable(self) -> bool:
        return self in {
            self.PROVIDER_RATE_LIMITED,
            self.CLI_TIMEOUT,
            self.CLI_FAILED,
            self.INVALID_MODEL_OUTPUT,
            self.SCREENPLAY_OUTPUT_INCOMPLETE,
            self.WORKER_LOST,
        }


class AnalysisValidationCode(StrEnum):
    INVALID_SCHEMA = "invalid_schema"
    INVALID_TEXT = "invalid_text"
    INVALID_EVIDENCE = "invalid_evidence"
    INVALID_TIME_RANGE = "invalid_time_range"
    DUPLICATE_IDENTIFIER = "duplicate_identifier"
    LIMIT_EXCEEDED = "limit_exceeded"
