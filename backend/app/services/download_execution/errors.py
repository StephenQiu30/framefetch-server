from __future__ import annotations

from app.services.downloads.rules.content_restrictions import ContentRestriction
from app.services.downloads.rules.enums import DownloadErrorCode
from app.services.provider_failures import ProviderFailure


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


class LegacyContextChanged(RuntimeError):
    code = "client_context_mismatch"

    def __init__(self) -> None:
        self.failure = ProviderFailure.for_code(self.code)
        super().__init__(self.code)


_RUNNER_CODES = {
    **{
        reason.value: DownloadErrorCode.PROVIDER_CONTENT_RESTRICTED
        for reason in ContentRestriction
    },
    "download_timeout": DownloadErrorCode.DOWNLOAD_TIMEOUT,
    "inspection_timeout": DownloadErrorCode.INSPECTION_TIMEOUT,
    "inspection_failed": DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
    "format_unavailable": DownloadErrorCode.FORMAT_UNAVAILABLE,
    "transcode_required": DownloadErrorCode.TRANSCODE_REQUIRED,
    "media_validation_failed": DownloadErrorCode.MEDIA_VALIDATION_FAILED,
    "invalid_artifact": DownloadErrorCode.MEDIA_VALIDATION_FAILED,
    "media_probe_failed": DownloadErrorCode.MEDIA_VALIDATION_FAILED,
    "invalid_artifact_path": DownloadErrorCode.MEDIA_VALIDATION_FAILED,
    "invalid_runner_response": DownloadErrorCode.MEDIA_VALIDATION_FAILED,
    "workspace_limit_exceeded": DownloadErrorCode.OUTPUT_LIMIT_EXCEEDED,
    "output_limit_exceeded": DownloadErrorCode.OUTPUT_LIMIT_EXCEEDED,
    "source_changed": DownloadErrorCode.UNSUPPORTED_SOURCE,
    "unsupported_source": DownloadErrorCode.UNSUPPORTED_SOURCE,
    "unsupported_url": DownloadErrorCode.UNSUPPORTED_SOURCE,
    "credential_required": DownloadErrorCode.PROVIDER_AUTH_REQUIRED,
    "provider_session_not_allowed": (
        DownloadErrorCode.PROVIDER_ACCESS_POLICY_NOT_ALLOWED
    ),
    "credential_expired": DownloadErrorCode.PROVIDER_SESSION_EXPIRED,
    "credential_rejected": DownloadErrorCode.PROVIDER_SESSION_EXPIRED,
    "credential_revoked": DownloadErrorCode.FORMAT_UNAVAILABLE,
    "egress_challenged": DownloadErrorCode.PROVIDER_VERIFICATION_FAILED,
    "pot_required": DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
    "pot_rejected": DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
    "client_context_mismatch": DownloadErrorCode.FORMAT_UNAVAILABLE,
    "provider_rate_limited": DownloadErrorCode.PROVIDER_RATE_LIMITED,
    "provider_geo_restricted": DownloadErrorCode.PROVIDER_GEO_RESTRICTED,
    "provider_link_unavailable": DownloadErrorCode.PROVIDER_LINK_UNAVAILABLE,
    "provider_media_unsupported": DownloadErrorCode.PROVIDER_MEDIA_UNSUPPORTED,
    "content_deleted": DownloadErrorCode.PROVIDER_LINK_UNAVAILABLE,
    "content_private": DownloadErrorCode.PROVIDER_CONTENT_RESTRICTED,
    "content_not_entitled": DownloadErrorCode.PROVIDER_CONTENT_RESTRICTED,
    "content_entitlement_unknown": DownloadErrorCode.PROVIDER_CONTENT_RESTRICTED,
    "drm_protected": DownloadErrorCode.PROVIDER_DRM_PROTECTED,
    "provider_unsupported": DownloadErrorCode.PROVIDER_UNSUPPORTED,
    "pot_provider_unavailable": DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
    "pot_provider_release_mismatch": DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
    "provider_session_unavailable": DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
    "provider_session_not_ready": DownloadErrorCode.PROVIDER_SESSION_NOT_READY,
    "egress_denied": DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
    "network_transient": DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
    "upstream_unclassified": DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
    "protocol_unavailable": DownloadErrorCode.FORMAT_UNAVAILABLE,
    "extractor_regression": DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
    "download_failed": DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
    "runner_dependency_unavailable": DownloadErrorCode.WORKER_LOST,
    "runner_unavailable": DownloadErrorCode.WORKER_LOST,
    "runner_restarted": DownloadErrorCode.WORKER_LOST,
    "runner_release_mismatch": DownloadErrorCode.WORKER_LOST,
    "runner_release_changed": DownloadErrorCode.WORKER_LOST,
    "runner_busy": DownloadErrorCode.WORKER_LOST,
    "task_not_found": DownloadErrorCode.WORKER_LOST,
    "cancelled": DownloadErrorCode.CANCELLED,
}


def classify_runner_failure(error: BaseException) -> DownloadErrorCode:
    code = getattr(error, "code", None)
    if isinstance(code, str):
        known = _RUNNER_CODES.get(code)
        if known is not None:
            return known
        if code.startswith("provider_"):
            return DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE
        return DownloadErrorCode.WORKER_LOST
    return DownloadErrorCode.WORKER_LOST
