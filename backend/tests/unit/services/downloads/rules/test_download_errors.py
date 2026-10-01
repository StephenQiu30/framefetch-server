from app.services.downloads.rules.enums import DownloadErrorCode


def test_error_codes_are_stable_snake_case_values() -> None:
    assert {code.value for code in DownloadErrorCode} == {
        "cancelled",
        "download_timeout",
        "format_unavailable",
        "internal_error",
        "media_validation_failed",
        "output_limit_exceeded",
        "network_blocked",
        "challenge",
        "login_required",
        "identity_unavailable",
        "rate_limited",
        "context_changed",
        "content_unavailable",
        "content_protected",
        "extractor_broken",
        "transient",
        "invalid_input",
        "runtime_unavailable",
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
    assert DownloadErrorCode.TRANSIENT.retryable is True
    assert DownloadErrorCode.TRANSIENT.retryable is True
    assert DownloadErrorCode.LOGIN_REQUIRED.retryable is False
    assert DownloadErrorCode.CONTENT_PROTECTED.retryable is False
    assert DownloadErrorCode.TRANSCODE_REQUIRED.retryable is False
