from __future__ import annotations

import math
from enum import StrEnum


class StreamKind(StrEnum):
    MUXED = "muxed"
    VIDEO = "video"
    AUDIO = "audio"


class MediaKind(StrEnum):
    VIDEO = "video"
    IMAGE_GALLERY = "image_gallery"
    VIDEO_COLLECTION = "video_collection"


class Container(StrEnum):
    MP4 = "mp4"
    WEBM = "webm"
    ZIP = "zip"
    OTHER = "other"


class ContainerPreference(StrEnum):
    MP4 = "mp4"
    WEBM = "webm"
    SOURCE = "source"


class DynamicRange(StrEnum):
    SDR = "sdr"
    HDR = "hdr"


class VideoCodecFamily(StrEnum):
    H264 = "h264"
    HEVC = "hevc"
    VP9 = "vp9"
    AV1 = "av1"
    OTHER = "other"


class AudioCodecFamily(StrEnum):
    NONE = "none"
    AAC = "aac"
    OPUS = "opus"
    VORBIS = "vorbis"
    OTHER = "other"


class CompatibilityProfile(StrEnum):
    BALANCED = "balanced"
    QUALITY = "quality"
    SMALLEST = "smallest"


class FpsBucket(StrEnum):
    FPS_30 = "fps_30"
    FPS_60 = "fps_60"
    ABOVE_60 = "above_60"

    @classmethod
    def from_fps(cls, fps: float) -> FpsBucket:
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("fps must be a positive finite number")
        if fps <= 30.01:
            return cls.FPS_30
        if fps <= 60.01:
            return cls.FPS_60
        return cls.ABOVE_60


class DownloadStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DownloadSourceKind(StrEnum):
    REMOTE_PROVIDER = "remote_provider"
    BROWSER_IMPORT = "browser_import"


class DownloadStage(StrEnum):
    REVALIDATING = "revalidating"
    DOWNLOADING = "downloading"
    REMUXING = "remuxing"
    VERIFYING = "verifying"
    UPLOADING = "uploading"


class DownloadErrorCode(StrEnum):
    CANCELLED = "cancelled"
    DOWNLOAD_TIMEOUT = "download_timeout"
    FORMAT_UNAVAILABLE = "format_unavailable"
    INSPECTION_TIMEOUT = "inspection_timeout"
    INTERNAL_ERROR = "internal_error"
    MEDIA_VALIDATION_FAILED = "media_validation_failed"
    OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"
    PROVIDER_ACCESS_POLICY_NOT_ALLOWED = "provider_access_policy_not_allowed"
    PROVIDER_AUTH_REQUIRED = "provider_auth_required"
    PROVIDER_CONTENT_RESTRICTED = "provider_content_restricted"
    PROVIDER_DRM_PROTECTED = "provider_drm_protected"
    PROVIDER_GEO_RESTRICTED = "provider_geo_restricted"
    PROVIDER_GUEST_CONTEXT_REQUIRED = "provider_guest_context_required"
    PROVIDER_LINK_UNAVAILABLE = "provider_link_unavailable"
    PROVIDER_MEDIA_UNSUPPORTED = "provider_media_unsupported"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_SESSION_EXPIRED = "provider_session_expired"
    PROVIDER_SESSION_NOT_READY = "provider_session_not_ready"
    PROVIDER_TEMPORARILY_UNAVAILABLE = "provider_temporarily_unavailable"
    PROVIDER_UNSUPPORTED = "provider_unsupported"
    PROVIDER_VERIFICATION_FAILED = "provider_verification_failed"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    TEMP_SPACE_EXHAUSTED = "temp_space_exhausted"
    TRANSCODE_REQUIRED = "transcode_required"
    UNSUPPORTED_SOURCE = "unsupported_source"
    WORKER_LOST = "worker_lost"

    @property
    def retryable(self) -> bool:
        return self in {
            self.DOWNLOAD_TIMEOUT,
            self.INSPECTION_TIMEOUT,
            self.PROVIDER_RATE_LIMITED,
            self.PROVIDER_GUEST_CONTEXT_REQUIRED,
            self.PROVIDER_TEMPORARILY_UNAVAILABLE,
            self.STORAGE_UNAVAILABLE,
            self.TEMP_SPACE_EXHAUSTED,
            self.WORKER_LOST,
        }
