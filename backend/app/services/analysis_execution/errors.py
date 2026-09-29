from __future__ import annotations

from app.services.analysis.rules.enums import AnalysisErrorCode, AnalysisStage


class AnalysisOwnershipLost(RuntimeError):
    pass


class AnalysisLeaseLost(RuntimeError):
    pass


class AnalysisPersistenceUnavailable(RuntimeError):
    pass


class AnalysisPersistenceRejected(RuntimeError):
    """Persistence rejected otherwise valid output due to a schema invariant."""


class AnalysisSourceUnavailable(RuntimeError):
    pass


class AnalysisExecutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AnalysisArtifactError(AnalysisExecutionError):
    pass


class AnalysisOutcomeUnknown(AnalysisExecutionError):
    """A journaled model call started but its result was never recorded."""

    def __init__(self) -> None:
        super().__init__("analysis_outcome_unknown")


_ERROR_CODES = {
    "analysis_cli_unavailable": AnalysisErrorCode.CLI_UNAVAILABLE,
    "analysis_cli_unsupported": AnalysisErrorCode.CLI_UNSUPPORTED,
    "analysis_cli_not_authenticated": AnalysisErrorCode.CLI_NOT_AUTHENTICATED,
    "analysis_sandbox_unavailable": AnalysisErrorCode.SANDBOX_UNAVAILABLE,
    "analysis_media_invalid": AnalysisErrorCode.MEDIA_INVALID,
    "analysis_provider_rate_limited": AnalysisErrorCode.PROVIDER_RATE_LIMITED,
    "analysis_provider_usage_limited": AnalysisErrorCode.PROVIDER_USAGE_LIMITED,
    "analysis_cli_timeout": AnalysisErrorCode.CLI_TIMEOUT,
    "analysis_cli_failed": AnalysisErrorCode.CLI_FAILED,
    "invalid_model_output": AnalysisErrorCode.INVALID_MODEL_OUTPUT,
    "analysis_resource_limit": AnalysisErrorCode.RESOURCE_LIMIT,
    "artifact_integrity_failed": AnalysisErrorCode.INPUT_ARTIFACT_UNAVAILABLE,
    "input_artifact_unavailable": AnalysisErrorCode.INPUT_ARTIFACT_UNAVAILABLE,
    "invalid_media_artifact": AnalysisErrorCode.MEDIA_INVALID,
    "analysis_outcome_unknown": AnalysisErrorCode.OUTCOME_UNKNOWN,
}


def classify_analysis_failure(
    error: BaseException, stage: AnalysisStage
) -> AnalysisErrorCode:
    del stage
    code = getattr(error, "code", None)
    if isinstance(code, str) and code in _ERROR_CODES:
        return _ERROR_CODES[code]
    if code in {
        "media_dependency_unavailable",
        "artifact_storage_unavailable",
        "invalid_analysis_workspace",
    }:
        return AnalysisErrorCode.WORKER_LOST
    return AnalysisErrorCode.CLI_FAILED
