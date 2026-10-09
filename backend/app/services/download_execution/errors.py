from __future__ import annotations

from app.services.downloads.rules.enums import DownloadErrorCode
from app.services.provider_failures import (
    FailureClass,
    FailureEvidenceKind,
    FailurePhase,
    ProviderFailure,
    failure_definition,
)


class ExecutionPersistenceUnavailable(RuntimeError):
    pass


class ExecutionSourceUnavailable(RuntimeError):
    pass


class ExecutionOwnershipLost(RuntimeError):
    pass


class LeaseLost(RuntimeError):
    pass


class LeaseInfrastructureError(RuntimeError):
    pass


class ArtifactValidationError(RuntimeError):
    pass


_RUNNER_CODES = {
    "media_validation_failed": DownloadErrorCode.MEDIA_VALIDATION_FAILED,
    "invalid_artifact": DownloadErrorCode.MEDIA_VALIDATION_FAILED,
    "media_probe_failed": DownloadErrorCode.MEDIA_VALIDATION_FAILED,
    "invalid_artifact_path": DownloadErrorCode.MEDIA_VALIDATION_FAILED,
    "invalid_runner_response": DownloadErrorCode.RUNTIME_UNAVAILABLE,
    "workspace_limit_exceeded": DownloadErrorCode.OUTPUT_LIMIT_EXCEEDED,
    "output_limit_exceeded": DownloadErrorCode.OUTPUT_LIMIT_EXCEEDED,
    "cancelled": DownloadErrorCode.CANCELLED,
}


def classify_runner_failure(error: BaseException) -> DownloadErrorCode:
    code = getattr(error, "code", None)
    if isinstance(code, str):
        known = _RUNNER_CODES.get(code)
        if known is not None:
            return known
        failure = getattr(error, "failure", None)
        if (
            isinstance(failure, ProviderFailure)
            and failure.failure_class is FailureClass.EXTRACTOR_BROKEN
            and failure.phase is FailurePhase.VALIDATE
            and failure.evidence_kind is FailureEvidenceKind.LOCAL_VALIDATION
        ):
            return DownloadErrorCode.MEDIA_VALIDATION_FAILED
        kind, _, _ = failure_definition(code)
        return DownloadErrorCode(kind.value)
    return DownloadErrorCode.RUNTIME_UNAVAILABLE
