"""Typed configuration shared by API, workers and media runner."""

from __future__ import annotations

import re
import tempfile
from functools import lru_cache
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.identifiers import RightsStatementVersion, UrlEncryptionKeyId
from app.services.provider_types import ProviderAccessMode, ProviderKey
from app.services.quotas import QuotaPolicy
from app.services.site_sessions import known_session_sites
from app.workers.runner.provider_instances import validated_instance_hosts


class QuotaLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_active_per_owner: int = Field(default=5, ge=1)
    daily_tasks: int = Field(default=50, ge=1)
    daily_bytes: int = Field(default=100 * 1024**3, ge=1)
    storage_bytes: int = Field(default=100 * 1024**3, ge=1)
    daily_analysis_attempts: int = Field(default=60, ge=1)

    def policy(self, **execution_limits: int) -> QuotaPolicy:
        return QuotaPolicy(**self.model_dump(), **execution_limits)


RateLimitOperation = Literal[
    "avatar_upload",
    "login",
    "register",
    "registration_code",
    "registration_code_verify",
    "inspect",
    "download",
    "download_retry",
    "media_import",
    "media_import_upload",
    "document_import",
    "document_import_upload",
    "analysis",
    "analysis_retry",
]


class RateLimitPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    limit: int = Field(ge=1, le=100_000)
    window_seconds: int = Field(ge=1, le=86400)


def default_rate_limits() -> dict[RateLimitOperation, RateLimitPolicy]:
    return {
        "avatar_upload": RateLimitPolicy(limit=10, window_seconds=60),
        "login": RateLimitPolicy(limit=10, window_seconds=60),
        "registration_code": RateLimitPolicy(limit=5, window_seconds=3600),
        "registration_code_verify": RateLimitPolicy(limit=10, window_seconds=60),
        "register": RateLimitPolicy(limit=5, window_seconds=3600),
        "inspect": RateLimitPolicy(limit=20, window_seconds=60),
        "download": RateLimitPolicy(limit=10, window_seconds=60),
        "download_retry": RateLimitPolicy(limit=5, window_seconds=60),
        "media_import": RateLimitPolicy(limit=10, window_seconds=60),
        "media_import_upload": RateLimitPolicy(limit=30, window_seconds=60),
        "document_import": RateLimitPolicy(limit=10, window_seconds=60),
        "document_import_upload": RateLimitPolicy(limit=30, window_seconds=60),
        "analysis": RateLimitPolicy(limit=5, window_seconds=60),
        "analysis_retry": RateLimitPolicy(limit=5, window_seconds=60),
    }


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_URL_ENCRYPTION_KEY = "ZGV2ZWxvcG1lbnQtdXJsLWtleS0zMi1ieXRlcyEhISE="


def _default_analysis_workspace_root() -> Path:
    return Path(tempfile.gettempdir()) / "framefetch-analysis"


class Settings(BaseSettings):
    """Load one validated configuration model from the root environment."""

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    service_role: Literal[
        "api",
        "outbox",
        "download-worker",
        "import-worker",
        "analysis-worker",
        "report-worker",
        "provider-canary",
        "provider-sources",
        "provider-guest",
        "session-broker",
    ] = "api"
    app_host: str = "0.0.0.0"
    app_port: int = Field(default=8111, ge=1, le=65535)
    app_version: str = "0.2.0"
    readiness_timeout_seconds: float = Field(default=2.0, ge=0.1, le=10)
    request_max_bytes: int = Field(default=256 * 1024, ge=1024, le=4 * 1024 * 1024)
    request_timeout_seconds: float = Field(default=180, ge=1, le=300)
    trusted_proxy_cidrs: tuple[str, ...] = ("127.0.0.0/8", "::1/128")
    trusted_frontend_proxy_ip: IPv4Address | IPv6Address | None = None
    rate_limit_policies: dict[RateLimitOperation, RateLimitPolicy] = Field(
        default_factory=dict
    )
    metrics_access_key: SecretStr = SecretStr(
        "development-metrics-access-key-change-me"
    )

    database_url: str = "postgresql+asyncpg://video:video@localhost:5432/video"
    # Only the session broker and the host source receive this key.
    site_session_encryption_key: SecretStr | None = None
    # Runner -> broker and broker -> browser use independent HMAC secrets.
    site_session_rpc_secret: SecretStr | None = None
    site_session_browser_secret: SecretStr | None = None
    site_session_browser_url: str = "http://session-browser:19300"
    site_session_scan_seconds: int = Field(default=15, ge=5, le=60)
    site_session_keepalive_seconds: int = Field(default=1800, ge=600, le=6 * 3600)
    site_session_keepalive_jitter_seconds: int = Field(default=300, ge=0, le=1800)
    site_session_coordination_url: str = "redis://provider-lease-redis:6379/0"
    site_session_lease_seconds: int = Field(default=600, ge=60, le=3600)
    site_session_source_sites: tuple[str, ...] = Field(
        default_factory=known_session_sites
    )
    site_session_source_profiles: dict[str, str] = Field(default_factory=dict)

    @field_validator("site_session_source_sites")
    @classmethod
    def validate_source_sites(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if set(value) - set(known_session_sites()):
            raise ValueError("source sites must be registered session sites")
        return tuple(dict.fromkeys(value))

    site_session_source_interval_seconds: int = Field(default=60, ge=30, le=3600)

    @field_validator("site_session_source_profiles")
    @classmethod
    def validate_source_profiles(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) - set(known_session_sites()):
            raise ValueError("source profile sites must be registered session sites")
        if any(
            re.fullmatch(r"(?:Default|Profile [1-9][0-9]*)", v) is None
            for v in value.values()
        ):
            raise ValueError("source profiles must name a Chrome profile directory")
        return value

    provider_source_root: Path = Path("/run/provider-sources")

    @field_validator("site_session_encryption_key", mode="before")
    @classmethod
    def validate_encryption_key(cls, value: object, info: ValidationInfo) -> object:
        if value is None or value == "":
            return None
        raw = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        try:
            Fernet(raw.encode("ascii"))
        except (ValueError, UnicodeError):
            raise ValueError(
                f"{str(info.field_name).upper()} must be a Fernet key"
            ) from None
        return value

    rabbitmq_url: str = "amqp://video-api:video-api-secret@localhost:5673/video"
    rabbitmq_vhost: str = Field(
        default="video",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    rabbitmq_exchange: str = "video.events"
    download_queue: str = "video.download"
    download_routing_key: Literal["download.requested"] = "download.requested"
    analysis_queue: str = "video.analysis"
    analysis_routing_key: Literal["analysis.requested"] = "analysis.requested"
    analysis_report_queue: str = "video.analysis-report"
    analysis_report_routing_key: Literal["analysis.report.publish.requested"] = (
        "analysis.report.publish.requested"
    )
    import_queue: str = "video.import"
    import_routing_key: Literal["content.import.verify.requested"] = (
        "content.import.verify.requested"
    )
    rabbitmq_connection_timeout_seconds: float = Field(default=10, ge=1, le=60)
    rabbitmq_publish_timeout_seconds: float = Field(default=10, ge=1, le=60)
    rabbitmq_heartbeat_seconds: int = Field(default=60, ge=10, le=600)
    rabbitmq_reconnect_interval_seconds: float = Field(default=5, ge=1, le=60)
    worker_prefetch: int = Field(default=2, ge=1, le=32)
    download_worker_threads: int = Field(default=4, ge=1, le=64)
    outbox_batch_size: int = Field(default=50, ge=1, le=200)
    outbox_poll_interval_seconds: float = Field(default=1.0, ge=0.1, le=60)
    operation_log_retention_days: int = Field(default=180, ge=30, le=3650)
    operation_log_purge_interval_seconds: float = Field(default=3600, ge=60, le=86400)
    operation_log_purge_batch_size: int = Field(default=5000, ge=100, le=50_000)
    redis_url: str | None = None

    minio_endpoint: str = "localhost:19190"
    minio_public_endpoint: str = "127.0.0.1:19190"
    minio_local_browser_endpoint: str | None = None
    minio_access_key: SecretStr = SecretStr("video-access")
    minio_secret_key: SecretStr = SecretStr("video-secret-change-me")
    minio_internal_secure: bool = False
    minio_public_secure: bool = False
    minio_local_browser_secure: bool = False
    minio_region: str = "us-east-1"
    minio_bucket: str = "video-artifacts"

    auth_jwt_secret: SecretStr = SecretStr("development-jwt-secret-change-me-32-bytes")
    auth_jwt_issuer: str = Field(default="video-server", min_length=1, max_length=128)
    auth_jwt_audience: str = Field(default="video-web", min_length=1, max_length=128)
    auth_web_cookie_name: str = Field(
        default="video_web_session",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    auth_web_idle_ttl_seconds: int = Field(default=604_800, ge=60, le=31_536_000)
    auth_web_absolute_ttl_seconds: int = Field(default=2_592_000, ge=60, le=31_536_000)

    @model_validator(mode="after")
    def validate_web_session_lifetime(self) -> Settings:
        if self.auth_web_idle_ttl_seconds > self.auth_web_absolute_ttl_seconds:
            raise ValueError("Web idle lifetime must not exceed absolute lifetime")
        return self

    auth_access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    auth_refresh_token_ttl_seconds: int = Field(
        default=2_592_000, ge=3600, le=31_536_000
    )
    smtp_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_tls_mode: Literal["starttls", "tls", "none"] = "starttls"
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from_email: EmailStr | None = None
    smtp_from_name: str = Field(default="帧取", max_length=100, pattern=r"^[^\r\n]*$")

    @model_validator(mode="after")
    def validate_smtp(self) -> Settings:
        if self.smtp_enabled:
            if not self.smtp_host.strip() or self.smtp_from_email is None:
                raise ValueError("SMTP_HOST and SMTP_FROM_EMAIL are required")
            if bool(self.smtp_username) != bool(self.smtp_password.get_secret_value()):
                raise ValueError("SMTP credentials must be configured together")
            if self.smtp_tls_mode == "none" and (
                self.app_env == "production" or self.smtp_username
            ):
                raise ValueError(
                    "SMTP TLS is required for production or authentication"
                )
        return self

    auth_bootstrap_admin_email: EmailStr | None = None
    auth_bootstrap_admin_secret: SecretStr = SecretStr(
        "development-admin-bootstrap-secret-change-me"
    )
    request_fingerprint_secret: SecretStr = SecretStr(
        "development-fingerprint-secret-change-me"
    )
    url_encryption_key: SecretStr = SecretStr(DEFAULT_URL_ENCRYPTION_KEY)
    url_encryption_key_id: str = Field(
        default=UrlEncryptionKeyId.FERNET,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z0-9_-]+$",
    )

    runner_base_url: str = "http://localhost:19100"
    # One Runner serves every site with a deployment session (046). A site with a
    # session record never falls back to the anonymous Runner.
    session_runner_base_url: str | None = None
    runner_guest_base_urls: dict[ProviderKey, str] = Field(default_factory=dict)
    runner_workspace_root: Path = Path("/work")
    runner_hmac_secret: SecretStr = SecretStr("development-runner-secret-change-me")
    provider_canary_targets: SecretStr = SecretStr("[]")
    provider_verified_keys: frozenset[str] = frozenset()
    peertube_allowed_instances: frozenset[str] = frozenset()
    provider_canary_metadata_interval_seconds: int = Field(
        default=21_600, ge=300, le=604_800
    )
    provider_canary_media_interval_seconds: int = Field(
        default=86_400, ge=300, le=2_592_000
    )
    provider_canary_poll_seconds: float = Field(default=60, ge=5, le=3600)
    runner_signature_ttl_seconds: int = Field(default=30, ge=5, le=300)
    inspect_timeout_seconds: int = Field(default=150, ge=1, le=300)
    download_timeout_seconds: int = Field(default=7200, ge=1, le=7200)
    max_video_duration_seconds: int = Field(default=86400, ge=1, le=86400)
    max_file_size_bytes: int = Field(default=20 * 1024**3, ge=1, le=20 * 1024**3)
    max_workspace_size_bytes: int = Field(default=40 * 1024**3, ge=1, le=40 * 1024**3)
    download_thumbnail_ffmpeg_binary: Path = Path("ffmpeg")
    download_thumbnail_timeout_seconds: float = Field(default=15, ge=1, le=60)
    download_thumbnail_max_bytes: int = Field(
        default=2_000_000, ge=1024, le=10 * 1024**2
    )
    quota_limits: QuotaLimits = Field(default_factory=QuotaLimits)
    document_normalized_max_characters: int = Field(
        default=2_000_000, ge=1, le=2_000_000
    )
    analysis_report_max_bytes: int = Field(
        default=16 * 1024**2, ge=1024, le=64 * 1024**2
    )
    media_import_enabled: bool = True
    document_import_enabled: bool = True
    media_import_max_bytes: int = Field(default=2 * 1024**3, ge=1024, le=20 * 1024**3)
    document_import_max_bytes: int = Field(
        default=50 * 1024**2, ge=1024, le=512 * 1024**2
    )
    document_preview_max_bytes: int = Field(
        default=1 * 1024**2, ge=1024, le=1 * 1024**2
    )
    document_preview_max_characters: int = Field(
        default=1_000_000, ge=1_000, le=1_000_000
    )
    import_upload_session_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    import_upload_part_size_bytes: int = Field(
        default=32 * 1024**2, ge=5 * 1024**2, le=5 * 1024**3
    )
    import_upload_max_parts: int = Field(default=1000, ge=1, le=10_000)
    import_upload_max_concurrency: int = Field(default=4, ge=1, le=16)
    import_quarantine_retention_days: int = Field(default=1, ge=1, le=7)
    import_rights_statement_version: str = Field(
        default=RightsStatementVersion.CONTENT,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    import_workspace_root: Path = Path("./.import-work")
    import_ffprobe_binary: Path = Path("ffprobe")
    import_ffprobe_timeout_seconds: float = Field(default=30, ge=1, le=300)
    import_max_probe_output_bytes: int = Field(
        default=256 * 1024, ge=1024, le=16 * 1024**2
    )
    import_max_video_width: int = Field(default=8192, ge=16, le=32768)
    import_max_video_height: int = Field(default=8192, ge=16, le=32768)
    import_max_media_streams: int = Field(default=32, ge=1, le=1024)
    import_recovery_interval_seconds: float = Field(default=5, ge=1, le=300)
    import_recovery_batch_size: int = Field(default=50, ge=1, le=200)
    import_workspace_grace_seconds: int = Field(default=1800, ge=60, le=86400)
    import_artifact_orphan_grace_seconds: int = Field(default=3600, ge=300, le=604800)
    inspection_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    article_discovery_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    article_discovery_timeout_seconds: float = Field(default=12, ge=1, le=30)
    article_discovery_max_response_bytes: int = Field(
        default=4 * 1024**2, ge=64 * 1024, le=4 * 1024**2
    )
    article_discovery_max_items: int = Field(default=24, ge=1, le=100)
    article_discovery_min_interval_seconds: float = Field(default=1, ge=0.5, le=10)
    article_discovery_proxy_url: str | None = None
    artifact_delete_timeout_seconds: float = Field(default=30, ge=1, le=300)
    artifact_download_url_ttl_seconds: int = Field(default=300, ge=60, le=3600)
    job_lease_seconds: int = Field(default=60, ge=15, le=600)
    heartbeat_interval_seconds: int = Field(default=15, ge=5, le=120)
    max_download_attempts: int = Field(default=3, ge=1, le=10)
    max_analysis_attempts: int = Field(default=3, ge=1, le=10)
    download_queued_recovery_seconds: int = Field(default=60, ge=15, le=3600)
    download_workspace_gc_seconds: int = Field(default=86_400, ge=300, le=2_592_000)
    analysis_max_runs_per_job: int = Field(default=10, ge=1, le=100)
    analysis_queued_recovery_seconds: int = Field(default=60, ge=15, le=3600)
    analysis_worker_heartbeat_seconds: float = Field(default=10, ge=1, le=60)
    analysis_worker_stale_seconds: int = Field(default=45, ge=5, le=300)
    analysis_manual_retry_min_interval_seconds: int = Field(default=30, ge=0, le=86400)
    analysis_manual_retries_per_day: int = Field(default=20, ge=1, le=1000)
    analysis_report_gc_interval_seconds: float = Field(default=300, ge=5, le=86400)
    analysis_report_gc_batch_size: int = Field(default=50, ge=1, le=200)
    analysis_report_orphan_grace_seconds: int = Field(default=3600, ge=300, le=604800)
    websocket_max_connections: int = Field(default=1000, ge=1, le=100000)
    websocket_max_connections_per_owner: int = Field(default=4, ge=1, le=100)
    websocket_auth_recheck_seconds: float = Field(default=15, ge=1, le=300)

    analysis_enabled: bool = False
    screenplay_analysis_enabled: bool = False
    analysis_workspace_root: Path = Field(
        default_factory=_default_analysis_workspace_root
    )
    analysis_codex_binary: Path = Path("codex")
    analysis_claude_binary: Path = Path("claude")
    analysis_ffmpeg_binary: Path = Path("ffmpeg")
    analysis_ffprobe_binary: Path = Path("ffprobe")
    analysis_timeout_seconds: float = Field(default=900, ge=1, le=3600)
    analysis_max_stdout_bytes: int = Field(default=2 * 1024**2, ge=1024)
    analysis_max_stderr_bytes: int = Field(default=128 * 1024, ge=1024)
    analysis_max_workspace_bytes: int = Field(default=4 * 1024**3, ge=1024)
    analysis_max_workspace_files: int = Field(default=512, ge=8, le=4096)
    analysis_max_screenplay_bytes: int = Field(
        default=2 * 1024**2, ge=1024, le=50 * 1024**2
    )
    analysis_screenplay_single_call_characters: int = Field(
        default=120_000, ge=1_000, le=500_000
    )
    analysis_screenplay_rewrite_glossary_chunk_characters: int = Field(
        default=20_000, ge=1_000, le=50_000
    )
    analysis_screenplay_rewrite_chunk_characters: int = Field(
        default=8_000, ge=1_000, le=50_000
    )
    analysis_max_screenplay_rewrite_chunks: int = Field(default=128, ge=1, le=512)
    analysis_screenplay_rewrite_context_characters: int = Field(
        default=1_000, ge=100, le=4_000
    )
    analysis_max_screenplay_rewrite_output_characters: int = Field(
        default=400_000, ge=8_000, le=2_000_000
    )
    analysis_screenplay_rewrite_chunk_call_attempts: int = Field(default=2, ge=1, le=5)
    analysis_screenplay_rewrite_chunk_retry_delay_seconds: float = Field(
        default=1.0, ge=0.1, le=30
    )
    analysis_max_frames: int = Field(default=256, ge=1, le=1024)
    analysis_max_image_bytes: int = Field(default=20 * 1024**2, ge=1024)
    analysis_workspace_poll_seconds: float = Field(default=0.25, ge=0.05, le=5)
    analysis_terminate_grace_seconds: float = Field(default=2, ge=0.1, le=30)
    analysis_claude_max_turns: int = Field(default=40, ge=1, le=100)
    analysis_database_url: str = "postgresql+asyncpg://video:video@localhost:5432/video"
    analysis_rabbitmq_url: str = (
        "amqp://video-analysis:video-analysis-secret@localhost:5673/video"
    )
    analysis_minio_endpoint: str = "localhost:19190"

    @field_validator("database_url", "analysis_database_url")
    @classmethod
    def require_async_postgresql(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("database URLs must use postgresql+asyncpg")
        return value

    @field_validator("runner_workspace_root")
    @classmethod
    def resolve_workspace(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("analysis_workspace_root")
    @classmethod
    def absolute_analysis_workspace(cls, value: Path) -> Path:
        return value.expanduser().absolute()

    @field_validator("import_workspace_root")
    @classmethod
    def absolute_import_workspace(cls, value: Path) -> Path:
        return value.expanduser().absolute()

    @field_validator("auth_bootstrap_admin_email", "smtp_from_email", mode="before")
    @classmethod
    def empty_bootstrap_admin_email_to_none(cls, value: object) -> object | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        try:
            return tuple(str(ip_network(cidr, strict=False)) for cidr in value)
        except ValueError as exc:
            raise ValueError("TRUSTED_PROXY_CIDRS contains an invalid network") from exc

    @field_validator("minio_local_browser_endpoint", mode="before")
    @classmethod
    def empty_local_browser_endpoint_to_none(cls, value: object) -> object | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("minio_public_endpoint", "minio_local_browser_endpoint")
    @classmethod
    def validate_minio_browser_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value != value.strip():
            raise ValueError("MinIO browser endpoint must be a host with optional port")
        try:
            parsed = urlsplit(f"//{value}")
            _ = parsed.port
        except ValueError as exc:
            raise ValueError(
                "MinIO browser endpoint must be a host with optional port"
            ) from exc
        if (
            parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("MinIO browser endpoint must be a host with optional port")
        host = parsed.hostname
        try:
            ip_address(host)
        except ValueError:
            labels = host.split(".")
            if any(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
                for label in labels
            ):
                raise ValueError(
                    "MinIO browser endpoint must be a host with optional port"
                ) from None
        return value

    @field_validator("minio_local_browser_endpoint")
    @classmethod
    def require_loopback_local_browser_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        host = urlsplit(f"//{value}").hostname
        if host == "localhost":
            return value
        try:
            if host is not None and ip_address(host).is_loopback:
                return value
        except ValueError:
            pass
        raise ValueError(
            "MINIO_LOCAL_BROWSER_ENDPOINT must use localhost or a loopback IP"
        )

    @field_validator("session_runner_base_url")
    @classmethod
    def validate_session_runner_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return _internal_http_url(value)

    @field_validator("runner_guest_base_urls")
    @classmethod
    def validate_runner_guest_urls(
        cls, value: dict[ProviderKey, str]
    ) -> dict[ProviderKey, str]:
        validated = {
            provider: _internal_http_url(endpoint)
            for provider, endpoint in value.items()
        }
        if len(set(validated.values())) != len(validated):
            raise ValueError("guest runner URLs must be provider-isolated")
        return validated

    @model_validator(mode="after")
    def validate_runner_route_declarations(self) -> Settings:
        from app.workers.runner.provider_registry import provider_profile_for_key

        isolated = {self.runner_base_url, self.session_runner_base_url}
        if set(self.runner_guest_base_urls.values()) & isolated:
            raise ValueError(
                "guest runners must be isolated from anonymous and session runners"
            )
        if self.session_runner_base_url == self.runner_base_url:
            raise ValueError("the session runner must be isolated from anonymous")
        for guest_key in self.runner_guest_base_urls:
            if (
                ProviderAccessMode.GUEST
                not in provider_profile_for_key(guest_key).access_modes
            ):
                raise ValueError("provider does not allow guest access")
        return self

    @field_validator("article_discovery_proxy_url", mode="before")
    @classmethod
    def validate_article_discovery_proxy(cls, value: object) -> object | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str):
            return value
        try:
            parsed = urlsplit(value)
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("ARTICLE_DISCOVERY_PROXY_URL is invalid") from exc
        if (
            parsed.scheme != "http"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("ARTICLE_DISCOVERY_PROXY_URL must be an HTTP authority")
        return value.rstrip("/")

    @field_validator("url_encryption_key")
    @classmethod
    def validate_fernet_key(cls, value: SecretStr) -> SecretStr:
        try:
            Fernet(value.get_secret_value().encode())
        except (TypeError, ValueError) as exc:
            raise ValueError("URL_ENCRYPTION_KEY must be a Fernet key") from exc
        return value

    @field_validator("provider_verified_keys")
    @classmethod
    def validate_provider_verified_keys(cls, value: frozenset[str]) -> frozenset[str]:
        if any(re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", key) is None for key in value):
            raise ValueError("PROVIDER_VERIFIED_KEYS contains an invalid key")
        return value

    @field_validator("peertube_allowed_instances")
    @classmethod
    def validate_peertube_instances(cls, value: frozenset[str]) -> frozenset[str]:
        return validated_instance_hosts(value)

    @field_validator(
        "auth_jwt_secret",
        "auth_bootstrap_admin_secret",
        "request_fingerprint_secret",
        "runner_hmac_secret",
        "site_session_rpc_secret",
        "site_session_browser_secret",
    )
    @classmethod
    def validate_signing_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value().encode()) < 32:
            raise ValueError("signing secrets must contain at least 32 bytes")
        return value

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> Settings:
        if self.analysis_worker_stale_seconds <= self.analysis_worker_heartbeat_seconds:
            raise ValueError(
                "analysis worker stale window must exceed its heartbeat interval"
            )
        if self.heartbeat_interval_seconds >= self.job_lease_seconds:
            raise ValueError("worker heartbeat interval must be shorter than its lease")
        if self.import_workspace_grace_seconds <= self.job_lease_seconds:
            raise ValueError("import workspace grace must exceed its lease")
        upload_capacity = (
            self.import_upload_part_size_bytes * self.import_upload_max_parts
        )
        if max(self.media_import_max_bytes, self.document_import_max_bytes) > (
            upload_capacity
        ):
            raise ValueError("import multipart budget is smaller than an import limit")
        if self.app_env != "production":
            return self
        secret_values: list[str] = []
        if self.service_role == "api":
            secret_values.extend(
                (
                    self.auth_jwt_secret.get_secret_value(),
                    self.auth_bootstrap_admin_secret.get_secret_value(),
                    self.request_fingerprint_secret.get_secret_value(),
                    self.runner_hmac_secret.get_secret_value(),
                    self.metrics_access_key.get_secret_value(),
                    self.minio_access_key.get_secret_value(),
                    self.minio_secret_key.get_secret_value(),
                )
            )
        elif self.service_role == "download-worker":
            secret_values.extend(
                (
                    self.request_fingerprint_secret.get_secret_value(),
                    self.runner_hmac_secret.get_secret_value(),
                    self.minio_access_key.get_secret_value(),
                    self.minio_secret_key.get_secret_value(),
                )
            )
        elif self.service_role == "import-worker":
            secret_values.extend(
                (
                    self.minio_access_key.get_secret_value(),
                    self.minio_secret_key.get_secret_value(),
                )
            )
        elif self.service_role == "analysis-worker":
            secret_values.extend(
                (
                    self.minio_access_key.get_secret_value(),
                    self.minio_secret_key.get_secret_value(),
                )
            )
        elif self.service_role == "report-worker":
            secret_values.extend(
                (
                    self.minio_access_key.get_secret_value(),
                    self.minio_secret_key.get_secret_value(),
                )
            )
        elif self.service_role == "provider-canary":
            secret_values.extend(
                (
                    self.runner_hmac_secret.get_secret_value(),
                    self.minio_access_key.get_secret_value(),
                    self.minio_secret_key.get_secret_value(),
                )
            )
        insecure = any(
            value.startswith(("development-", "video-")) or "replace-with" in value
            for value in secret_values
        )
        rabbitmq_url = ""
        if self.service_role == "analysis-worker":
            rabbitmq_url = self.analysis_rabbitmq_url
        elif self.service_role not in {
            "provider-canary",
            "provider-sources",
            "provider-guest",
            "session-broker",
        }:
            rabbitmq_url = self.rabbitmq_url
        insecure_urls = any(
            marker in f"{self.database_url} {rabbitmq_url}"
            for marker in ("video:video@", "replace-with", "-secret@")
        )
        # Only processes that encrypt or decrypt URLs/provider keys receive this
        # secret. Queue forwarding, import verification and report publication do
        # not need it and must be able to start without it.
        default_url_key = (
            self.service_role
            in {
                "api",
                "download-worker",
                "provider-canary",
                "analysis-worker",
                "provider-guest",
            }
            and self.url_encryption_key.get_secret_value() == DEFAULT_URL_ENCRYPTION_KEY
        )
        if insecure or insecure_urls or default_url_key:
            raise ValueError("production secrets must be explicitly configured")
        if self.service_role == "api" and not self.redis_url:
            raise ValueError("production API requires REDIS_URL")
        if self.service_role == "api" and self.auth_bootstrap_admin_email is None:
            raise ValueError("production API requires AUTH_BOOTSTRAP_ADMIN_EMAIL")
        return self

    def analysis_minio_credentials(self) -> tuple[SecretStr, SecretStr]:
        """Return the shared MinIO credentials used by every service."""
        return self.minio_access_key, self.minio_secret_key

    def minio_public_origin(self) -> str:
        """Return the validated browser-visible object storage origin."""
        scheme = "https" if self.minio_public_secure else "http"
        return f"{scheme}://{self.minio_public_endpoint}"

    def minio_local_browser_origin(self) -> str | None:
        """Return the optional loopback storage origin used by local Web clients."""
        if self.minio_local_browser_endpoint is None:
            return None
        scheme = "https" if self.minio_local_browser_secure else "http"
        return f"{scheme}://{self.minio_local_browser_endpoint}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def get_settings_for_role(
    role: Literal[
        "api",
        "outbox",
        "download-worker",
        "import-worker",
        "analysis-worker",
        "report-worker",
        "provider-canary",
        "provider-guest",
    ],
) -> Settings:
    return Settings(service_role=role)


def _internal_http_url(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("runner URL is invalid") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("runner URL must be an internal HTTP URL")
    return endpoint.rstrip("/")
