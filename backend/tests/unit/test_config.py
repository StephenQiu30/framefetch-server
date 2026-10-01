from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from app.core.config import DEFAULT_URL_ENCRYPTION_KEY, REPOSITORY_ROOT, Settings
from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError


def test_port_bounds_are_validated() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="test", app_port=0)


@pytest.mark.parametrize(
    "field",
    ("database_url", "analysis_database_url"),
)
def test_database_urls_require_async_postgresql(field: str) -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+asyncpg"):
        Settings(app_env="test", _env_file=None, **{field: "sqlite:///video.db"})


def test_download_limits_are_validated() -> None:
    defaults = Settings(app_env="test", _env_file=None)

    assert defaults.request_timeout_seconds == 180
    assert defaults.inspect_timeout_seconds == 120
    assert defaults.download_timeout_seconds == 7_200
    assert defaults.max_video_duration_seconds == 86_400
    assert defaults.max_file_size_bytes == 20 * 1024**3

    with pytest.raises(ValidationError):
        Settings(app_env="test", max_file_size_bytes=0)

    with pytest.raises(ValidationError):
        Settings(app_env="test", download_timeout_seconds=0)

    with pytest.raises(ValidationError):
        Settings(app_env="test", download_worker_threads=0)


def test_local_import_defaults_and_bounds() -> None:
    settings = Settings(app_env="test", _env_file=None)

    assert settings.media_import_enabled is True
    assert settings.document_import_enabled is True
    assert settings.analysis_enabled is False
    assert settings.screenplay_analysis_enabled is False
    assert settings.analysis_max_screenplay_bytes == 2 * 1024**2
    assert settings.analysis_screenplay_rewrite_chunk_characters == 8_000
    assert settings.analysis_screenplay_rewrite_glossary_chunk_characters == 20_000
    assert settings.analysis_max_screenplay_rewrite_chunks == 128
    assert settings.analysis_screenplay_rewrite_context_characters == 1_000
    assert settings.analysis_max_screenplay_rewrite_output_characters == 400_000
    assert settings.analysis_screenplay_rewrite_chunk_call_attempts == 2
    assert settings.analysis_screenplay_rewrite_chunk_retry_delay_seconds == 1.0
    assert settings.media_import_max_bytes == 2 * 1024**3
    assert settings.document_import_max_bytes == 50 * 1024**2
    assert settings.import_upload_session_ttl_seconds == 900
    assert settings.import_upload_part_size_bytes == 32 * 1024**2
    assert settings.import_upload_max_parts == 1000
    assert settings.import_upload_max_concurrency == 4
    assert settings.import_rights_statement_version == "content-rights"
    assert settings.import_ffprobe_timeout_seconds == 30
    assert settings.import_max_probe_output_bytes == 256 * 1024
    assert settings.import_max_video_width == 8192
    assert settings.import_max_video_height == 8192
    assert settings.import_max_media_streams == 32
    assert settings.import_recovery_batch_size == 50
    assert settings.import_workspace_grace_seconds == 1800
    assert settings.import_artifact_orphan_grace_seconds == 3600

    for field in (
        "media_import_max_bytes",
        "document_import_max_bytes",
        "import_upload_session_ttl_seconds",
        "import_upload_part_size_bytes",
        "import_upload_max_parts",
        "import_upload_max_concurrency",
        "import_ffprobe_timeout_seconds",
        "import_max_probe_output_bytes",
        "import_max_video_width",
        "import_max_video_height",
        "import_max_media_streams",
        "import_recovery_interval_seconds",
        "import_recovery_batch_size",
        "import_workspace_grace_seconds",
        "import_artifact_orphan_grace_seconds",
    ):
        with pytest.raises(ValidationError):
            Settings(app_env="test", _env_file=None, **{field: 0})

    with pytest.raises(ValidationError):
        Settings(
            app_env="test",
            _env_file=None,
            import_rights_statement_version="Invalid Rights Version",
        )


def test_local_import_limit_must_fit_multipart_budget() -> None:
    with pytest.raises(ValidationError, match="multipart budget"):
        Settings(
            app_env="test",
            _env_file=None,
            media_import_max_bytes=20 * 1024**3,
            import_upload_part_size_bytes=5 * 1024**2,
            import_upload_max_parts=1000,
        )


def test_minio_public_endpoint_is_safe_for_browser_policy() -> None:
    settings = Settings(
        app_env="test",
        minio_public_endpoint="storage.example.com:9443",
        minio_public_secure=True,
        _env_file=None,
    )

    assert settings.minio_public_origin() == "https://storage.example.com:9443"
    for endpoint in (
        "https://storage.example.com",
        "storage.example.com/path",
        "storage.example.com;script-src",
    ):
        with pytest.raises(ValidationError, match="MinIO browser endpoint"):
            Settings(
                app_env="test",
                minio_public_endpoint=endpoint,
                _env_file=None,
            )


def test_local_browser_minio_endpoint_is_optional_and_validated() -> None:
    settings = Settings(
        app_env="test",
        minio_local_browser_endpoint="127.0.0.1:9000",
        _env_file=None,
    )

    assert settings.minio_local_browser_origin() == "http://127.0.0.1:9000"
    assert Settings(app_env="test", _env_file=None).minio_local_browser_origin() is None
    assert (
        Settings(
            app_env="test",
            minio_local_browser_endpoint="",
            _env_file=None,
        ).minio_local_browser_origin()
        is None
    )
    with pytest.raises(ValidationError, match="MinIO browser endpoint"):
        Settings(
            app_env="test",
            minio_local_browser_endpoint="http://127.0.0.1:9000/path",
            _env_file=None,
        )
    with pytest.raises(ValidationError, match="must use localhost or a loopback IP"):
        Settings(
            app_env="test",
            minio_local_browser_endpoint="storage.example.com:9000",
            _env_file=None,
        )


def test_import_worker_runtime_limits_are_relationally_safe() -> None:
    with pytest.raises(ValidationError, match="heartbeat interval"):
        Settings(
            app_env="test",
            _env_file=None,
            job_lease_seconds=30,
            heartbeat_interval_seconds=30,
        )
    with pytest.raises(ValidationError, match="workspace grace"):
        Settings(
            app_env="test",
            _env_file=None,
            job_lease_seconds=60,
            import_workspace_grace_seconds=60,
        )


def test_persistent_artifacts_have_no_retention_ttl_setting() -> None:
    defaults = Settings(app_env="test", _env_file=None)

    assert "artifact_ttl_seconds" not in Settings.model_fields
    assert "analysis_report_ttl_seconds" not in Settings.model_fields
    assert defaults.artifact_download_url_ttl_seconds == 300


def test_signing_secrets_require_adequate_entropy_capacity() -> None:
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(app_env="test", auth_jwt_secret=SecretStr("too-short"))


def test_peertube_allowlist_accepts_only_exact_domain_names() -> None:
    settings = Settings(
        app_env="test",
        peertube_allowed_instances=frozenset({"VIDEO.EXAMPLE.COM"}),
    )

    assert settings.peertube_allowed_instances == frozenset({"video.example.com"})
    for invalid in ("*.example.com", "https://video.example.com", "127.0.0.1"):
        with pytest.raises(ValidationError, match="invalid host"):
            Settings(app_env="test", peertube_allowed_instances=frozenset({invalid}))


def test_session_runner_endpoint_is_one_isolated_internal_url() -> None:
    settings = Settings(
        app_env="test",
        _env_file=None,
        session_runner_base_url="http://session-runner:19100/",
    )
    assert settings.session_runner_base_url == "http://session-runner:19100"
    assert Settings(app_env="test", _env_file=None).session_runner_base_url is None
    for invalid in (
        "https://public.example/runner",
        "http://user:pass@session-runner:19100",
        "http://session-runner:19100/path",
    ):
        with pytest.raises(ValidationError):
            Settings(app_env="test", _env_file=None, session_runner_base_url=invalid)


def test_article_discovery_proxy_is_an_http_authority() -> None:
    settings = Settings(
        app_env="test",
        _env_file=None,
        article_discovery_proxy_url="http://egress-proxy:3128/",
    )

    assert settings.article_discovery_proxy_url == "http://egress-proxy:3128"
    for invalid in (
        "https://egress-proxy:3128",
        "http://user:secret@egress-proxy:3128",
        "http://egress-proxy:3128/path",
    ):
        with pytest.raises(ValidationError, match="ARTICLE_DISCOVERY_PROXY_URL"):
            Settings(
                app_env="test",
                _env_file=None,
                article_discovery_proxy_url=invalid,
            )


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_article_discovery_proxy_is_normalized_to_none(value: str) -> None:
    settings = Settings(
        app_env="test",
        _env_file=None,
        article_discovery_proxy_url=value,
    )

    assert settings.article_discovery_proxy_url is None


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_bootstrap_admin_email_is_normalized_to_none(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_EMAIL", value)

    settings = Settings(app_env="test")

    assert settings.auth_bootstrap_admin_email is None


def test_bootstrap_admin_email_retains_email_validation() -> None:
    settings = Settings(app_env="test", auth_bootstrap_admin_email="admin@example.com")

    assert settings.auth_bootstrap_admin_email == "admin@example.com"
    with pytest.raises(ValidationError):
        Settings(app_env="test", auth_bootstrap_admin_email="not-an-email")


def test_proxy_networks_and_bootstrap_secret_are_validated() -> None:
    settings = Settings(
        app_env="test",
        trusted_proxy_cidrs=("127.0.0.1", "2001:db8::/32"),
        auth_bootstrap_admin_secret=SecretStr("s" * 32),
        _env_file=None,
    )

    assert settings.trusted_proxy_cidrs == ("127.0.0.1/32", "2001:db8::/32")
    with pytest.raises(ValidationError, match="TRUSTED_PROXY_CIDRS"):
        Settings(app_env="test", trusted_proxy_cidrs=("not-a-network",))
    with pytest.raises(ValidationError, match="signing secrets"):
        Settings(
            app_env="test",
            auth_bootstrap_admin_secret=SecretStr("too-short"),
            _env_file=None,
        )


def test_production_rejects_development_secrets() -> None:
    with pytest.raises(ValidationError, match="production secrets"):
        Settings(app_env="production")


def test_production_accepts_explicit_secrets() -> None:
    settings = Settings(
        app_env="production",
        database_url="postgresql+asyncpg://app:StrongDbPass123@postgres:5432/video",
        rabbitmq_url="amqp://app:StrongMqPass123@rabbitmq:5672/",
        redis_url="redis://redis:6379/0",
        auth_jwt_secret=SecretStr("s" * 48),
        request_fingerprint_secret=SecretStr("f" * 48),
        url_encryption_key=SecretStr("MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="),
        runner_hmac_secret=SecretStr("r" * 48),
        minio_access_key=SecretStr("production-access"),
        minio_secret_key=SecretStr("m" * 48),
        metrics_access_key=SecretStr("k" * 48),
        auth_bootstrap_admin_email="admin@example.com",
        auth_bootstrap_admin_secret=SecretStr("b" * 48),
        analysis_enabled=True,
    )

    assert settings.app_env == "production"
    assert settings.analysis_enabled is True


def test_production_rejects_default_url_encryption_key() -> None:
    with pytest.raises(ValidationError, match="production secrets"):
        Settings(
            app_env="production",
            database_url="postgresql+asyncpg://app:db-secret@postgres:5432/video",
            rabbitmq_url="amqp://app:mq-secret@rabbitmq:5672/",
            auth_jwt_secret=SecretStr("s" * 48),
            request_fingerprint_secret=SecretStr("f" * 48),
            runner_hmac_secret=SecretStr("r" * 48),
            minio_access_key=SecretStr("production-access"),
            minio_secret_key=SecretStr("m" * 48),
            analysis_enabled=True,
        )


@pytest.mark.parametrize("role", ("api", "worker", "analysis-worker"))
def test_production_url_key_required_only_for_consumers(role: str) -> None:
    kwargs = dict(
        _env_file=None,
        app_env="production",
        service_role=role,
        database_url="postgresql+asyncpg://app:db-password@postgres:5432/video",
        rabbitmq_url="amqp://app:mq-password@rabbitmq:5672/",
        auth_jwt_secret="s" * 48,
        request_fingerprint_secret="f" * 48,
        runner_hmac_secret="r" * 48,
        minio_access_key="production-access",
        minio_secret_key="m" * 48,
        metrics_access_key="k" * 48,
        auth_bootstrap_admin_secret="a" * 48,
        auth_bootstrap_admin_email="admin@example.com",
        redis_url="redis://redis:6379/0",
    )
    with pytest.raises(ValidationError, match="production secrets"):
        Settings(**kwargs, url_encryption_key=DEFAULT_URL_ENCRYPTION_KEY)


def test_production_worker_requires_every_background_secret() -> None:
    """The merged worker needs the union of its components' secrets."""
    kwargs = dict(
        _env_file=None,
        app_env="production",
        service_role="worker",
        database_url="postgresql+asyncpg://app:db-password@postgres:5432/video",
        rabbitmq_url="amqp://app:mq-password@rabbitmq:5672/",
        request_fingerprint_secret="f" * 48,
        runner_hmac_secret="r" * 48,
        minio_access_key="production-access",
        minio_secret_key="m" * 48,
        url_encryption_key=Fernet.generate_key().decode(),
    )
    settings = Settings(**kwargs)
    assert settings.service_role == "worker"
    for missing in (
        "request_fingerprint_secret",
        "runner_hmac_secret",
        "minio_secret_key",
    ):
        values = {key: value for key, value in kwargs.items() if key != missing}
        with pytest.raises(ValidationError, match="production secrets"):
            Settings(**values)
    with pytest.raises(ValidationError, match="production secrets"):
        Settings(
            **{
                **kwargs,
                "rabbitmq_url": "amqp://video-worker:video-worker-secret@rabbitmq:5672/",
            }
        )


def test_analysis_settings_only_configure_host_binary_paths() -> None:
    settings = Settings(app_env="test", _env_file=None)

    assert settings.analysis_codex_binary == Path("codex")
    assert settings.analysis_claude_binary == Path("claude")
    assert "analysis_cli_provider" not in type(settings).model_fields
    assert "analysis_codex_model" not in type(settings).model_fields
    assert "analysis_claude_model" not in type(settings).model_fields
    assert "analysis_schema_version" not in type(settings).model_fields
    assert "analysis_prompt_version" not in type(settings).model_fields
    assert "localhost:5432" in settings.analysis_database_url
    assert not any("openai" in name for name in type(settings).model_fields)


def test_analysis_workspace_defaults_outside_repository() -> None:
    settings = Settings(app_env="test", _env_file=None)

    assert (
        settings.analysis_workspace_root
        == (Path(tempfile.gettempdir()) / "framefetch-analysis").absolute()
    )
    assert not settings.analysis_workspace_root.is_relative_to(
        Path(__file__).resolve().parents[3]
    )


def test_analysis_worker_uses_shared_minio_credentials() -> None:
    access = SecretStr("shared-access")
    secret = SecretStr("shared-secret")
    settings = Settings(
        app_env="test",
        service_role="analysis-worker",
        minio_access_key=access,
        minio_secret_key=secret,
        _env_file=None,
    )

    assert settings.analysis_minio_credentials() == (access, secret)


def test_environment_file_stays_at_repository_root_after_module_move() -> None:
    repository = Path(__file__).resolve().parents[3]
    assert REPOSITORY_ROOT == repository
    assert Settings.model_config["env_file"] == repository / ".env"
