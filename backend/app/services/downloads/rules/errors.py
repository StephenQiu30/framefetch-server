from __future__ import annotations

from app.services.downloads.rules.enums import DownloadErrorCode


class FormatSelectionError(ValueError):
    def __init__(self, code: DownloadErrorCode) -> None:
        if code not in {
            DownloadErrorCode.FORMAT_UNAVAILABLE,
            DownloadErrorCode.TRANSCODE_REQUIRED,
        }:
            raise ValueError("invalid format selection error code")
        self.code = code
        super().__init__(code.value)
