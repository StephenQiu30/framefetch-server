from datetime import UTC, datetime

from app.core.db import Base
from app.repositories.downloads.recovery_repository import stale_jobs_statement
from app.repositories.outbox_repository import outbox_claim_statement
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable


def test_download_schema_contains_required_tables_and_columns() -> None:
    tables = Base.metadata.tables
    assert {
        "artifacts",
        "auth_sessions",
        "download_jobs",
        "media_formats",
        "media_import_attempts",
        "media_imports",
        "media_inspections",
        "outbox_events",
        "users",
        "provider_catalog_entries",
        "source_discoveries",
        "source_discovery_items",
    } <= set(tables)
    jobs = tables["download_jobs"]
    assert {
        "status",
        "stage",
        "progress",
        "attempt",
        "version",
        "lease_owner",
        "lease_expires_at",
        "heartbeat_at",
        "semantic_plan",
        "source_kind",
        "inspection_id",
        "format_id",
    } <= set(jobs.columns.keys())
    assert jobs.c.semantic_plan.type.compile(postgresql.dialect()) == "JSONB"
    assert jobs.c.inspection_id.nullable is True
    assert jobs.c.format_id.nullable is True
    assert "ix_download_jobs_created" in {index.name for index in jobs.indexes}
    active_request = next(
        index
        for index in jobs.indexes
        if index.name == "uq_download_jobs_owner_active_request"
    )
    assert active_request.unique is True
    assert "retry_wait" in str(active_request.dialect_options["postgresql"]["where"])
    assert {
        "username",
        "normalized_username",
        "email",
        "password_hash",
        "role",
        "is_active",
    } <= set(tables["users"].columns.keys())
    assert {"user_id", "token_hash", "expires_at"} <= set(
        tables["auth_sessions"].columns.keys()
    )
    assert not {
        "provider_canary_results",
        "provider_route_cooldowns",
        "resolution_attempts",
    } & set(tables)
    intents = tables["download_intents"]
    assert {"execution_context", "latest_failure"} <= set(intents.columns.keys())
    assert not {
        "resolution_plan",
        "next_strategy_id",
        "fence",
        "remaining_budget_ms",
        "attempt",
    } & set(intents.columns.keys())
    assert "execution_context" in jobs.columns
    assert "execution_access_context" not in jobs.columns
    catalog = tables["provider_catalog_entries"]
    assert {
        "key",
        "display_name",
        "sort_order",
        "is_visible",
        "is_deleted",
        "created_at",
        "updated_at",
    } <= set(catalog.columns.keys())
    media_imports = tables["media_imports"]
    assert {
        "owner_hash",
        "request_fingerprint",
        "rights_statement_version",
        "declared_sha256",
        "status",
        "attempt",
        "version",
    } <= set(media_imports.columns.keys())
    attempts = tables["media_import_attempts"]
    assert {
        "resource_id",
        "attempt",
        "object_key",
        "upload_id",
        "part_size_bytes",
        "part_count",
        "expires_at",
        "lease_owner",
        "lease_expires_at",
    } <= set(attempts.columns.keys())


def test_sensitive_url_is_not_a_plaintext_column() -> None:
    inspection = Base.metadata.tables["media_inspections"]
    assert "url" not in inspection.columns
    assert {"url_ciphertext", "url_nonce", "url_key_id"} <= set(
        inspection.columns.keys()
    )
    ddl = str(CreateTable(inspection).compile(dialect=postgresql.dialect()))
    assert "BYTEA" in ddl
    discovery = Base.metadata.tables["source_discoveries"]
    assert "url" not in discovery.columns
    assert {"url_ciphertext", "url_nonce", "url_key_id"} <= set(
        discovery.columns.keys()
    )
    items = Base.metadata.tables["source_discovery_items"]
    assert not {"url", "iframe_url", "cdn_url", "raw_html"} & set(items.columns.keys())


def test_constraints_cover_idempotency_progress_and_artifact_identity() -> None:
    dialect = postgresql.dialect()
    job_ddl = str(
        CreateTable(Base.metadata.tables["download_jobs"]).compile(dialect=dialect)
    )
    artifact_ddl = str(
        CreateTable(Base.metadata.tables["artifacts"]).compile(dialect=dialect)
    )
    user_ddl = str(CreateTable(Base.metadata.tables["users"]).compile(dialect=dialect))
    media_import_ddl = str(
        CreateTable(Base.metadata.tables["media_imports"]).compile(dialect=dialect)
    )
    import_attempt_ddl = str(
        CreateTable(Base.metadata.tables["media_import_attempts"]).compile(
            dialect=dialect
        )
    )
    assert "uq_download_jobs_owner_idempotency" in job_ddl
    assert "progress BETWEEN 0 AND 100" in job_ddl
    assert "ck_download_jobs_source_shape" in job_ddl
    assert "source_kind = 'remote_provider'" in job_ddl
    assert "source_kind = 'browser_import'" in job_ddl
    assert "uq_artifacts_job" in artifact_ddl
    assert "uq_artifacts_object" in artifact_ddl
    assert "expires_at" not in Base.metadata.tables["artifacts"].columns
    assert "expires_at" not in Base.metadata.tables["documents"].columns
    assert "expires_at" not in Base.metadata.tables["document_artifacts"].columns
    assert "expires_at" not in Base.metadata.tables["analysis_report_artifacts"].columns
    assert "retry_available_until" not in Base.metadata.tables["analysis_jobs"].columns
    assert "ix_artifacts_expires" not in {
        index.name for index in Base.metadata.tables["artifacts"].indexes
    }
    assert "ck_users_role" in user_ddl
    assert "uq_media_imports_owner_idempotency" in media_import_ddl
    assert "ck_media_imports_terminal_shape" in media_import_ddl
    assert "uq_media_import_attempts_object" in import_attempt_ddl
    assert "ck_media_import_attempts_verifying_shape" in import_attempt_ddl
    assert "ck_media_import_attempts_terminal_shape" in import_attempt_ddl


def test_postgres_claims_use_skip_locked_for_parallel_consumers() -> None:
    now = datetime(2026, 8, 6, tzinfo=UTC)
    dialect = postgresql.dialect()
    stale_sql = str(stale_jobs_statement(now, 10).compile(dialect=dialect))
    outbox_sql = str(outbox_claim_statement(now, 10).compile(dialect=dialect))
    assert "FOR UPDATE SKIP LOCKED" in stale_sql
    assert "FOR UPDATE SKIP LOCKED" in outbox_sql
    assert "download_jobs.source_kind =" in stale_sql
