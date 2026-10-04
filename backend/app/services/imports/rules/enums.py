from __future__ import annotations

from enum import StrEnum


class ContentKind(StrEnum):
    VIDEO = "video"
    SCREENPLAY = "screenplay"


class DeclaredOrigin(StrEnum):
    USER_FILE = "user_file"
    WECHAT_CHANNELS = "wechat_channels"


class ImportSourceFormat(StrEnum):
    MP4 = "mp4"
    DOCX = "docx"
    PDF = "pdf"
    TXT = "txt"
    MARKDOWN = "markdown"
    FOUNTAIN = "fountain"
    SRT = "srt"
    VTT = "vtt"

    @property
    def content_kind(self) -> ContentKind:
        if self is self.MP4:
            return ContentKind.VIDEO
        return ContentKind.SCREENPLAY

    @property
    def content_type(self) -> str:
        return {
            self.MP4: "video/mp4",
            self.DOCX: (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            self.PDF: "application/pdf",
            self.TXT: "text/plain; charset=utf-8",
            self.MARKDOWN: "text/markdown; charset=utf-8",
            self.FOUNTAIN: "text/plain; charset=utf-8",
            self.SRT: "application/x-subrip; charset=utf-8",
            self.VTT: "text/vtt; charset=utf-8",
        }[self]


class ImportStatus(StrEnum):
    UPLOADING = "uploading"
    VERIFYING = "verifying"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ImportErrorCode(StrEnum):
    STORAGE_UNAVAILABLE = "import_storage_unavailable"
    UPLOAD_SESSION_EXPIRED = "upload_session_expired"
    UPLOAD_INCOMPLETE = "upload_incomplete"
    SIZE_MISMATCH = "import_size_mismatch"
    SHA256_MISMATCH = "import_sha256_mismatch"
    VIDEO_INVALID = "video_import_invalid"
    DOCUMENT_FORMAT_UNSUPPORTED = "document_format_unsupported"
    DOCUMENT_ENCRYPTED = "document_encrypted"
    DOCUMENT_ARCHIVE_UNSAFE = "document_archive_unsafe"
    DOCUMENT_TEXT_UNAVAILABLE = "document_text_unavailable"
    DOCUMENT_STRUCTURE_INVALID = "document_structure_invalid"

    @property
    def retryable(self) -> bool:
        return self is self.STORAGE_UNAVAILABLE
