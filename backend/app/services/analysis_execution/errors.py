from __future__ import annotations

from app.services.analysis.rules.enums import AnalysisErrorCode


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
    def __init__(
        self,
        code: str,
        *,
        no_model_execution: bool = False,
        outcome_known: bool = False,
    ) -> None:
        self.code = code
        self.no_model_execution = no_model_execution
        self.outcome_known = outcome_known
        super().__init__(code)


class AnalysisArtifactError(AnalysisExecutionError):
    pass


class AnalysisOutcomeUnknown(AnalysisExecutionError):
    """A journaled model call started but its result was never recorded."""

    def __init__(self) -> None:
        super().__init__("analysis_outcome_unknown")


_ERROR_CODES = {item.value: item for item in AnalysisErrorCode} | {
    "artifact_integrity_failed": AnalysisErrorCode.INPUT_ARTIFACT_UNAVAILABLE,
    "invalid_media_artifact": AnalysisErrorCode.MEDIA_INVALID,
    "media_dependency_unavailable": AnalysisErrorCode.WORKER_LOST,
    "artifact_storage_unavailable": AnalysisErrorCode.WORKER_LOST,
    "invalid_analysis_workspace": AnalysisErrorCode.WORKER_LOST,
}


def classify_analysis_failure(error: BaseException) -> AnalysisErrorCode | None:
    """Normalize public failures; unrecognized infrastructure errors stay separate."""
    if isinstance(error, TimeoutError):
        return AnalysisErrorCode.CLI_TIMEOUT
    code = getattr(error, "code", None)
    return _ERROR_CODES.get(code) if isinstance(code, str) else None
