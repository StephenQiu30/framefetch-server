from app.services.downloads.rules.enums import DownloadErrorCode


def test_error_codes_are_stable_snake_case_values() -> None:
    assert {code.value for code in DownloadErrorCode} == {
        "cancelled",
        "download_timeout",
        "format_unavailable",
        "inspection_timeout",
        "internal_error",
        "media_validation_failed",
        "output_limit_exceeded",
        "provider_access_policy_not_allowed",
        "provider_auth_required",
        "provider_content_restricted",
        "provider_drm_protected",
        "provider_geo_restricted",
        "provider_guest_context_required",
        "provider_link_unavailable",
        "provider_media_unsupported",
        "provider_rate_limited",
        "provider_session_expired",
        "provider_session_not_ready",
        "provider_temporarily_unavailable",
        "provider_unsupported",
        "provider_verification_failed",
        "storage_unavailable",
        "temp_space_exhausted",
        "transcode_required",
        "unsupported_source",
        "worker_lost",
    }


def test_only_transient_errors_are_retryable() -> None:
    assert DownloadErrorCode.STORAGE_UNAVAILABLE.retryable is True
    assert DownloadErrorCode.WORKER_LOST.retryable is True
    assert DownloadErrorCode.DOWNLOAD_TIMEOUT.retryable is True
    assert DownloadErrorCode.FORMAT_UNAVAILABLE.retryable is False
    assert DownloadErrorCode.PROVIDER_RATE_LIMITED.retryable is True
    assert DownloadErrorCode.PROVIDER_GUEST_CONTEXT_REQUIRED.retryable is True
    assert DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE.retryable is True
    assert DownloadErrorCode.PROVIDER_AUTH_REQUIRED.retryable is False
    assert DownloadErrorCode.PROVIDER_DRM_PROTECTED.retryable is False
    assert DownloadErrorCode.TRANSCODE_REQUIRED.retryable is False
