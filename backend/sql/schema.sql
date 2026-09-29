-- Universal video downloader: current PostgreSQL schema.
-- The deployment operator applies this file to the existing project database.
-- Keep creation idempotent so both empty and already initialized volumes converge
-- on all currently required tables and indexes. This remains a current-state
-- schema, not a historical migration chain.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username VARCHAR(32) NOT NULL,
    normalized_username VARCHAR(64) NOT NULL,
    email VARCHAR(320) NOT NULL,
    password_hash VARCHAR(512) NOT NULL,
    role VARCHAR(16) NOT NULL DEFAULT 'user',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    avatar_data BYTEA,
    avatar_version UUID,
    quota_exempt BOOLEAN NOT NULL DEFAULT FALSE,
    quota_max_active_tasks INTEGER CHECK (quota_max_active_tasks > 0),
    quota_daily_tasks INTEGER CHECK (quota_daily_tasks > 0),
    quota_daily_bytes BIGINT CHECK (quota_daily_bytes > 0),
    quota_storage_bytes BIGINT CHECK (quota_storage_bytes > 0),
    quota_daily_analysis_attempts INTEGER CHECK (quota_daily_analysis_attempts > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_users_email UNIQUE (email),
    CONSTRAINT uq_users_normalized_username UNIQUE (normalized_username),
    CONSTRAINT ck_users_role CHECK (role IN ('admin', 'user'))
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_exempt BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_data BYTEA;
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_version UUID;
ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_max_active_tasks INTEGER CHECK (quota_max_active_tasks > 0);
ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_daily_tasks INTEGER CHECK (quota_daily_tasks > 0);
ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_daily_bytes BIGINT CHECK (quota_daily_bytes > 0);
ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_storage_bytes BIGINT CHECK (quota_storage_bytes > 0);
ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_daily_analysis_attempts INTEGER CHECK (quota_daily_analysis_attempts > 0);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_auth_sessions_token_hash UNIQUE (token_hash)
);

CREATE INDEX IF NOT EXISTS ix_auth_sessions_user ON auth_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_auth_sessions_expires ON auth_sessions (expires_at);

CREATE TABLE IF NOT EXISTS web_sessions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    idle_expires_at TIMESTAMPTZ NOT NULL,
    absolute_expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    CONSTRAINT ck_web_sessions_token_hash CHECK (length(token_hash) = 64),
    CONSTRAINT ck_web_sessions_lifetime CHECK (
        created_at <= last_seen_at AND last_seen_at < idle_expires_at
        AND idle_expires_at <= absolute_expires_at
    )
);
CREATE INDEX IF NOT EXISTS ix_web_sessions_user ON web_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_web_sessions_absolute_expires ON web_sessions (absolute_expires_at);

CREATE TABLE IF NOT EXISTS ai_provider_profiles (
    key VARCHAR(32) PRIMARY KEY,
    display_name VARCHAR(64) NOT NULL,
    engine VARCHAR(16) NOT NULL,
    auth_mode VARCHAR(16) NOT NULL,
    base_url VARCHAR(2048),
    model VARCHAR(128) NOT NULL,
    credential_ciphertext BYTEA,
    credential_key_id VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_ai_provider_engine CHECK (
        engine IN ('codex', 'claude', 'deepseek', 'openrouter', 'openai')
    ),
    CONSTRAINT ck_ai_provider_auth_mode CHECK (
        auth_mode IN ('host_login', 'api_key')
    ),
    CONSTRAINT ck_ai_provider_auth_shape CHECK (
        (
            auth_mode = 'host_login'
            AND base_url IS NULL
            AND credential_ciphertext IS NULL
            AND credential_key_id IS NULL
        ) OR (
            auth_mode = 'api_key'
            AND base_url IS NOT NULL
            AND credential_ciphertext IS NOT NULL
            AND credential_key_id IS NOT NULL
        )
    ),
    CONSTRAINT ck_ai_provider_local_codex_shape CHECK (
        key <> 'local-codex' OR (
            engine = 'codex'
            AND auth_mode = 'host_login'
            AND base_url IS NULL
            AND credential_ciphertext IS NULL
            AND credential_key_id IS NULL
        )
    )
);

ALTER TABLE ai_provider_profiles
    DROP CONSTRAINT IF EXISTS ck_ai_provider_engine;
ALTER TABLE ai_provider_profiles
    ADD CONSTRAINT ck_ai_provider_engine CHECK (
        engine IN ('codex', 'claude', 'deepseek', 'openrouter', 'openai')
    );
ALTER TABLE ai_provider_profiles
    DROP CONSTRAINT IF EXISTS ck_ai_provider_deepseek_auth;
ALTER TABLE ai_provider_profiles
    ADD CONSTRAINT ck_ai_provider_deepseek_auth CHECK (
        engine NOT IN ('deepseek', 'openrouter', 'openai') OR auth_mode = 'api_key'
    );

ALTER TABLE ai_provider_profiles
    DROP CONSTRAINT IF EXISTS ck_ai_provider_openrouter_endpoint;
ALTER TABLE ai_provider_profiles
    ADD CONSTRAINT ck_ai_provider_openrouter_endpoint CHECK (
        engine <> 'openrouter' OR base_url = 'https://openrouter.ai/api/v1'
    );

CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_provider_active
    ON ai_provider_profiles (is_active)
    WHERE is_active;

INSERT INTO ai_provider_profiles (
    key, display_name, engine, auth_mode, base_url, model,
    credential_ciphertext, credential_key_id, is_active
) VALUES (
    'local-codex', '本机 Codex', 'codex', 'host_login', NULL,
    'gpt-5.6-sol', NULL, NULL,
    NOT EXISTS (SELECT 1 FROM ai_provider_profiles WHERE is_active)
)
ON CONFLICT (key) DO UPDATE SET
    engine = 'codex',
    auth_mode = 'host_login',
    base_url = NULL,
    credential_ciphertext = NULL,
    credential_key_id = NULL,
    is_active = ai_provider_profiles.is_active
        OR NOT EXISTS (SELECT 1 FROM ai_provider_profiles WHERE is_active),
    updated_at = CURRENT_TIMESTAMP
WHERE ai_provider_profiles.engine IS DISTINCT FROM 'codex'
    OR ai_provider_profiles.auth_mode IS DISTINCT FROM 'host_login'
    OR ai_provider_profiles.base_url IS NOT NULL
    OR ai_provider_profiles.credential_ciphertext IS NOT NULL
    OR ai_provider_profiles.credential_key_id IS NOT NULL
    OR NOT EXISTS (SELECT 1 FROM ai_provider_profiles WHERE is_active);

ALTER TABLE ai_provider_profiles
    DROP CONSTRAINT IF EXISTS ck_ai_provider_local_codex_shape;
ALTER TABLE ai_provider_profiles
    ADD CONSTRAINT ck_ai_provider_local_codex_shape CHECK (
        key <> 'local-codex' OR (
            engine = 'codex'
            AND auth_mode = 'host_login'
            AND base_url IS NULL
            AND credential_ciphertext IS NULL
            AND credential_key_id IS NULL
        )
    );

CREATE TABLE IF NOT EXISTS provider_catalog_entries (
    key VARCHAR(32) PRIMARY KEY,
    display_name VARCHAR(64) NOT NULL,
    sort_order INTEGER NOT NULL,
    is_visible BOOLEAN NOT NULL DEFAULT TRUE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_provider_catalog_sort_order CHECK (
        sort_order BETWEEN 0 AND 10000
    )
);

INSERT INTO provider_catalog_entries (
    key, display_name, sort_order, is_visible, is_deleted
) VALUES
    ('youtube', 'YouTube', 10, TRUE, FALSE),
    ('bilibili', '哔哩哔哩', 20, TRUE, FALSE),
    ('douyin', '抖音', 30, TRUE, FALSE),
    ('tiktok', 'TikTok', 40, TRUE, FALSE),
    ('xiaohongshu', '小红书', 50, TRUE, FALSE),
    ('kuaishou', '快手', 60, TRUE, FALSE),
    ('vimeo', 'Vimeo', 70, TRUE, FALSE),
    ('x', 'X / Twitter', 80, TRUE, FALSE),
    ('instagram', 'Instagram', 90, TRUE, FALSE),
    ('facebook', 'Facebook', 100, TRUE, FALSE),
    ('twitch', 'Twitch', 110, TRUE, FALSE),
    ('reddit', 'Reddit', 120, TRUE, FALSE),
    ('pinterest', 'Pinterest', 130, TRUE, FALSE),
    ('weibo', '微博', 140, TRUE, FALSE),
    ('youku', '优酷', 150, TRUE, FALSE),
    ('qqvideo', '腾讯视频', 160, TRUE, FALSE),
    ('wechat_official_account_article', '微信公众号文章', 165, TRUE, FALSE),
    ('wechat_channels', '微信视频号', 170, TRUE, FALSE),
    ('snapchat', 'Snapchat Spotlight', 180, TRUE, FALSE),
    ('linkedin', 'LinkedIn', 190, TRUE, FALSE),
    ('telegram', 'Telegram', 200, TRUE, FALSE),
    ('kick', 'Kick', 210, TRUE, FALSE),
    ('tumblr', 'Tumblr', 220, TRUE, FALSE),
    ('hongguo_web', '红果短剧官方分享', 230, TRUE, FALSE)
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS media_inspections (
    id UUID PRIMARY KEY,
    owner_hash VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    url_ciphertext BYTEA NOT NULL,
    url_nonce BYTEA NOT NULL,
    url_key_id VARCHAR(64) NOT NULL,
    extractor_key VARCHAR(128) NOT NULL,
    provider_media_id VARCHAR(256) NOT NULL,
    title TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL,
    metadata JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_media_inspections_owner_idempotency
        UNIQUE (owner_hash, idempotency_key),
    CONSTRAINT ck_inspection_duration CHECK (duration_seconds >= 0)
);

ALTER TABLE media_inspections DROP CONSTRAINT IF EXISTS ck_inspection_duration;
ALTER TABLE media_inspections ADD CONSTRAINT ck_inspection_duration
    CHECK (duration_seconds >= 0);

CREATE INDEX IF NOT EXISTS ix_media_inspections_owner_expires
    ON media_inspections (owner_hash, expires_at);

CREATE TABLE IF NOT EXISTS source_discoveries (
    id UUID PRIMARY KEY,
    owner_hash VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    provider_key VARCHAR(64) NOT NULL,
    url_ciphertext BYTEA NOT NULL,
    url_nonce BYTEA NOT NULL,
    url_key_id VARCHAR(64) NOT NULL,
    source_fingerprint VARCHAR(64) NOT NULL,
    title TEXT NOT NULL,
    adapter_version VARCHAR(128) NOT NULL,
    status VARCHAR(24) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_source_discoveries_owner_idempotency
        UNIQUE (owner_hash, idempotency_key),
    CONSTRAINT ck_source_discoveries_status CHECK (status IN ('ready', 'empty'))
);

CREATE INDEX IF NOT EXISTS ix_source_discoveries_owner_expires
    ON source_discoveries (owner_hash, expires_at);

CREATE TABLE IF NOT EXISTS source_discovery_items (
    id UUID PRIMARY KEY,
    discovery_id UUID NOT NULL
        REFERENCES source_discoveries (id) ON DELETE CASCADE,
    item_ref UUID NOT NULL,
    position INTEGER NOT NULL,
    kind VARCHAR(32) NOT NULL,
    child_provider VARCHAR(64),
    title TEXT NOT NULL,
    duration_ms INTEGER,
    identity_evidence_hash VARCHAR(64) NOT NULL,
    decision_hint VARCHAR(24) NOT NULL,
    status VARCHAR(24) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_source_discovery_items_ref UNIQUE (discovery_id, item_ref),
    CONSTRAINT uq_source_discovery_items_identity
        UNIQUE (discovery_id, identity_evidence_hash),
    CONSTRAINT uq_source_discovery_items_position UNIQUE (discovery_id, position),
    CONSTRAINT ck_source_discovery_items_position CHECK (position >= 0),
    CONSTRAINT ck_source_discovery_items_kind CHECK (
        kind IN (
            'official_account_native', 'tencent_video',
            'wechat_channels', 'unknown'
        )
    ),
    CONSTRAINT ck_source_discovery_items_decision CHECK (
        decision_hint IN ('candidate', 'export_required', 'unsupported')
    ),
    CONSTRAINT ck_source_discovery_items_status CHECK (
        status IN ('ready', 'identity_unverified')
    )
);

CREATE INDEX IF NOT EXISTS ix_source_discovery_items_discovery
    ON source_discovery_items (discovery_id);

CREATE TABLE IF NOT EXISTS media_formats (
    id UUID PRIMARY KEY,
    inspection_id UUID NOT NULL
        REFERENCES media_inspections (id) ON DELETE CASCADE,
    display_name VARCHAR(128) NOT NULL,
    plan_fingerprint VARCHAR(64) NOT NULL,
    semantic_plan JSONB NOT NULL,
    provider_hints JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_media_formats_inspection_plan
        UNIQUE (inspection_id, plan_fingerprint)
);

CREATE INDEX IF NOT EXISTS ix_media_formats_inspection ON media_formats (inspection_id);
CREATE INDEX IF NOT EXISTS ix_media_formats_expires ON media_formats (expires_at);

CREATE TABLE IF NOT EXISTS media_thumbnails (
    inspection_id UUID PRIMARY KEY
        REFERENCES media_inspections (id) ON DELETE CASCADE,
    bucket VARCHAR(128) NOT NULL,
    object_key TEXT NOT NULL,
    content_type VARCHAR(64) NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_media_thumbnails_object UNIQUE (bucket, object_key),
    CONSTRAINT ck_media_thumbnails_size CHECK (size_bytes > 0),
    CONSTRAINT ck_media_thumbnails_sha256_length CHECK (length(sha256) = 64),
    CONSTRAINT ck_media_thumbnails_content_type CHECK (
        content_type IN ('image/avif','image/jpeg','image/png','image/webp')
    )
);

CREATE TABLE IF NOT EXISTS download_jobs (
    id UUID PRIMARY KEY,
    source_kind VARCHAR(32) NOT NULL DEFAULT 'remote_provider',
    inspection_id UUID REFERENCES media_inspections (id),
    format_id UUID REFERENCES media_formats (id),
    owner_hash VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    semantic_plan JSONB NOT NULL,
    execution_access_context JSONB,
    execution_context_attempt INTEGER,
    status VARCHAR(24) NOT NULL DEFAULT 'queued',
    stage VARCHAR(24),
    stage_rank INTEGER NOT NULL DEFAULT 0,
    progress INTEGER NOT NULL DEFAULT 0,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    version INTEGER NOT NULL DEFAULT 0,
    lease_owner VARCHAR(128),
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    retry_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_code VARCHAR(64),
    error_message VARCHAR(512),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_download_jobs_owner_idempotency
        UNIQUE (owner_hash, idempotency_key),
    CONSTRAINT ck_download_jobs_status CHECK (
        status IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed', 'cancelled')
    ),
    CONSTRAINT ck_download_jobs_progress CHECK (progress BETWEEN 0 AND 100),
    CONSTRAINT ck_download_jobs_attempt CHECK (attempt >= 0),
    CONSTRAINT ck_download_jobs_max_attempts CHECK (max_attempts > 0),
    CONSTRAINT ck_download_jobs_version CHECK (version >= 0),
    CONSTRAINT ck_download_jobs_stage_rank CHECK (stage_rank BETWEEN 0 AND 5),
    CONSTRAINT ck_download_jobs_source_shape CHECK (
        (
            source_kind = 'remote_provider'
            AND inspection_id IS NOT NULL
            AND format_id IS NOT NULL
        ) OR (
            source_kind = 'browser_import'
            AND inspection_id IS NULL
            AND format_id IS NULL
        )
    )
);

ALTER TABLE download_jobs
    ADD COLUMN IF NOT EXISTS source_kind VARCHAR(32);
ALTER TABLE download_jobs
    ADD COLUMN IF NOT EXISTS execution_access_context JSONB;
ALTER TABLE download_jobs
    ADD COLUMN IF NOT EXISTS execution_context_attempt INTEGER;
UPDATE download_jobs
SET source_kind = 'remote_provider'
WHERE source_kind IS NULL;
ALTER TABLE download_jobs
    ALTER COLUMN source_kind SET DEFAULT 'remote_provider';
ALTER TABLE download_jobs
    ALTER COLUMN source_kind SET NOT NULL;
ALTER TABLE download_jobs
    ALTER COLUMN inspection_id DROP NOT NULL;
ALTER TABLE download_jobs
    ALTER COLUMN format_id DROP NOT NULL;
ALTER TABLE download_jobs
    DROP CONSTRAINT IF EXISTS ck_download_jobs_source_shape;
ALTER TABLE download_jobs
    ADD CONSTRAINT ck_download_jobs_source_shape CHECK (
        (
            source_kind = 'remote_provider'
            AND inspection_id IS NOT NULL
            AND format_id IS NOT NULL
        ) OR (
            source_kind = 'browser_import'
            AND inspection_id IS NULL
            AND format_id IS NULL
        )
    );

CREATE INDEX IF NOT EXISTS ix_download_jobs_owner_created
    ON download_jobs (owner_hash, created_at);
CREATE INDEX IF NOT EXISTS ix_download_jobs_created ON download_jobs (created_at);
CREATE INDEX IF NOT EXISTS ix_download_jobs_claim ON download_jobs (status, retry_at);
CREATE INDEX IF NOT EXISTS ix_download_jobs_stale ON download_jobs (status, lease_expires_at);
CREATE INDEX IF NOT EXISTS ix_download_jobs_queued_recovery ON download_jobs (status, updated_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_download_jobs_owner_active_request
    ON download_jobs (owner_hash, request_fingerprint)
    WHERE source_kind = 'remote_provider'
      AND status IN ('queued','running','retry_wait');

CREATE TABLE IF NOT EXISTS media_imports (
    id UUID PRIMARY KEY REFERENCES download_jobs (id) ON DELETE CASCADE,
    owner_hash VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    source_format VARCHAR(32) NOT NULL,
    display_name VARCHAR(128) NOT NULL,
    content_type VARCHAR(128) NOT NULL,
    declared_size_bytes BIGINT NOT NULL,
    declared_sha256 VARCHAR(64) NOT NULL,
    rights_statement_version VARCHAR(64) NOT NULL,
    declared_origin VARCHAR(32) NOT NULL DEFAULT 'user_file',
    status VARCHAR(24) NOT NULL DEFAULT 'uploading',
    attempt INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR(64),
    version INTEGER NOT NULL DEFAULT 0,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_media_imports_owner_idempotency
        UNIQUE (owner_hash, idempotency_key),
    CONSTRAINT ck_media_imports_format CHECK (source_format = 'mp4'),
    CONSTRAINT ck_media_imports_content_type CHECK (content_type = 'video/mp4'),
    CONSTRAINT ck_media_imports_status CHECK (
        status IN ('uploading','verifying','ready','failed','cancelled','expired')
    ),
    CONSTRAINT ck_media_imports_declared_size CHECK (declared_size_bytes > 0),
    CONSTRAINT ck_media_imports_declared_sha256_length CHECK (
        length(declared_sha256) = 64
    ),
    CONSTRAINT ck_media_imports_attempt CHECK (attempt >= 0),
    CONSTRAINT ck_media_imports_version CHECK (version >= 0),
    CONSTRAINT ck_media_imports_declared_origin CHECK (
        declared_origin IN ('user_file','wechat_channels')
    ),
    CONSTRAINT ck_media_imports_terminal_shape CHECK (
        (status IN ('uploading','verifying') AND finished_at IS NULL) OR
        (status IN ('ready','failed','cancelled','expired') AND finished_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_media_imports_owner_created
    ON media_imports (owner_hash, created_at);
CREATE INDEX IF NOT EXISTS ix_media_imports_status_updated
    ON media_imports (status, updated_at);

ALTER TABLE media_imports ADD COLUMN IF NOT EXISTS declared_origin VARCHAR(32);
UPDATE media_imports SET declared_origin = 'user_file'
    WHERE declared_origin IS NULL;
ALTER TABLE media_imports ALTER COLUMN declared_origin SET DEFAULT 'user_file';
ALTER TABLE media_imports ALTER COLUMN declared_origin SET NOT NULL;
ALTER TABLE media_imports DROP CONSTRAINT IF EXISTS ck_media_imports_declared_origin;
ALTER TABLE media_imports ADD CONSTRAINT ck_media_imports_declared_origin CHECK (
    declared_origin IN ('user_file','wechat_channels')
);

CREATE TABLE IF NOT EXISTS download_thumbnails (
    job_id UUID PRIMARY KEY REFERENCES download_jobs(id) ON DELETE CASCADE,
    bucket VARCHAR(128) NOT NULL,
    object_key TEXT NOT NULL,
    content_type VARCHAR(64) NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_download_thumbnails_object UNIQUE (bucket, object_key),
    CONSTRAINT ck_download_thumbnails_size CHECK (size_bytes > 0),
    CONSTRAINT ck_download_thumbnails_sha256_length CHECK (length(sha256) = 64),
    CONSTRAINT ck_download_thumbnails_content_type CHECK (
        content_type IN ('image/avif','image/jpeg','image/png','image/webp')
    )
);

CREATE TABLE IF NOT EXISTS media_import_attempts (
    resource_id UUID NOT NULL
        REFERENCES media_imports (id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'uploading',
    object_key TEXT NOT NULL,
    upload_id TEXT,
    content_type VARCHAR(128) NOT NULL,
    declared_size_bytes BIGINT NOT NULL,
    actual_size_bytes BIGINT,
    part_size_bytes BIGINT NOT NULL,
    part_count INTEGER NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    error_code VARCHAR(64),
    lease_owner VARCHAR(128),
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (resource_id, attempt),
    CONSTRAINT uq_media_import_attempts_object UNIQUE (object_key),
    CONSTRAINT ck_media_import_attempts_attempt CHECK (attempt > 0),
    CONSTRAINT ck_media_import_attempts_status CHECK (
        status IN ('uploading','verifying','ready','failed','cancelled','expired')
    ),
    CONSTRAINT ck_media_import_attempts_content_type CHECK (
        content_type = 'video/mp4'
    ),
    CONSTRAINT ck_media_import_attempts_declared_size CHECK (
        declared_size_bytes > 0
    ),
    CONSTRAINT ck_media_import_attempts_actual_size CHECK (
        actual_size_bytes IS NULL OR actual_size_bytes > 0
    ),
    CONSTRAINT ck_media_import_attempts_part_size CHECK (
        part_size_bytes BETWEEN 5242880 AND 5368709120
    ),
    CONSTRAINT ck_media_import_attempts_part_count CHECK (
        part_count BETWEEN 1 AND 10000
    ),
    CONSTRAINT ck_media_import_attempts_verifying_shape CHECK (
        status <> 'verifying' OR actual_size_bytes IS NOT NULL
    ),
    CONSTRAINT ck_media_import_attempts_terminal_shape CHECK (
        (status IN ('uploading','verifying') AND finished_at IS NULL) OR
        (status IN ('ready','failed','cancelled','expired') AND finished_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_media_import_attempts_status_expires
    ON media_import_attempts (status, expires_at);
CREATE INDEX IF NOT EXISTS ix_media_import_attempts_stale
    ON media_import_attempts (status, lease_expires_at);

ALTER TABLE media_import_attempts
    DROP CONSTRAINT IF EXISTS ck_media_import_attempts_verifying_shape;
ALTER TABLE media_import_attempts
    ADD CONSTRAINT ck_media_import_attempts_verifying_shape CHECK (
        status <> 'verifying' OR actual_size_bytes IS NOT NULL
    );
ALTER TABLE media_import_attempts
    DROP CONSTRAINT IF EXISTS ck_media_import_attempts_terminal_shape;
ALTER TABLE media_import_attempts
    ADD CONSTRAINT ck_media_import_attempts_terminal_shape CHECK (
        (status IN ('uploading','verifying') AND finished_at IS NULL) OR
        (status IN ('ready','failed','cancelled','expired') AND finished_at IS NOT NULL)
    );

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY,
    owner_hash VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    title VARCHAR(128) NOT NULL,
    original_filename VARCHAR(128) NOT NULL,
    source_format VARCHAR(32) NOT NULL,
    content_type VARCHAR(128) NOT NULL,
    declared_size_bytes BIGINT NOT NULL,
    declared_sha256 VARCHAR(64) NOT NULL,
    rights_statement_version VARCHAR(64) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'uploading',
    attempt INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR(64),
    version INTEGER NOT NULL DEFAULT 0,
    detected_language VARCHAR(16),
    scene_count INTEGER,
    character_count INTEGER,
    text_sha256 VARCHAR(64),
    quality_warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    deleted_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_documents_owner_idempotency
        UNIQUE (owner_hash, idempotency_key),
    CONSTRAINT ck_documents_source_format CHECK (
        source_format IN ('docx','pdf','txt','markdown','fountain')
    ),
    CONSTRAINT ck_documents_status CHECK (
        status IN ('uploading','verifying','ready','failed','cancelled','expired')
    ),
    CONSTRAINT ck_documents_declared_size CHECK (declared_size_bytes > 0),
    CONSTRAINT ck_documents_declared_sha256_length CHECK (
        length(declared_sha256) = 64
    ),
    CONSTRAINT ck_documents_attempt CHECK (attempt >= 0),
    CONSTRAINT ck_documents_version CHECK (version >= 0),
    CONSTRAINT ck_documents_detected_language CHECK (
        detected_language IS NULL OR
        detected_language IN ('zh-CN','en-US','mixed','unknown')
    ),
    CONSTRAINT ck_documents_scene_count CHECK (
        scene_count IS NULL OR scene_count >= 0
    ),
    CONSTRAINT ck_documents_character_count CHECK (
        character_count IS NULL OR character_count > 0
    ),
    CONSTRAINT ck_documents_text_sha256_length CHECK (
        text_sha256 IS NULL OR length(text_sha256) = 64
    ),
    CONSTRAINT ck_documents_terminal_shape CHECK (
        (status IN ('uploading','verifying') AND finished_at IS NULL) OR
        (status IN ('ready','failed','cancelled','expired') AND finished_at IS NOT NULL)
    ),
    CONSTRAINT ck_documents_ready_shape CHECK (
        status <> 'ready' OR (
            detected_language IS NOT NULL AND scene_count IS NOT NULL AND
            character_count IS NOT NULL AND text_sha256 IS NOT NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_documents_owner_created
    ON documents (owner_hash, created_at);
CREATE INDEX IF NOT EXISTS ix_documents_status_updated
    ON documents (status, updated_at);
DROP INDEX IF EXISTS ix_documents_expires;
ALTER TABLE documents DROP COLUMN IF EXISTS expires_at;
ALTER TABLE documents DROP CONSTRAINT IF EXISTS ck_documents_ready_shape;
ALTER TABLE documents ADD CONSTRAINT ck_documents_ready_shape CHECK (
    status <> 'ready' OR (
        detected_language IS NOT NULL AND scene_count IS NOT NULL AND
        character_count IS NOT NULL AND text_sha256 IS NOT NULL
    )
);
CREATE TABLE IF NOT EXISTS document_import_attempts (
    resource_id UUID NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'uploading',
    object_key TEXT NOT NULL,
    upload_id TEXT,
    content_type VARCHAR(128) NOT NULL,
    declared_size_bytes BIGINT NOT NULL,
    actual_size_bytes BIGINT,
    part_size_bytes BIGINT NOT NULL,
    part_count INTEGER NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    error_code VARCHAR(64),
    lease_owner VARCHAR(128),
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (resource_id, attempt),
    CONSTRAINT uq_document_import_attempts_object UNIQUE (object_key),
    CONSTRAINT ck_document_import_attempts_attempt CHECK (attempt > 0),
    CONSTRAINT ck_document_import_attempts_status CHECK (
        status IN ('uploading','verifying','ready','failed','cancelled','expired')
    ),
    CONSTRAINT ck_document_import_attempts_declared_size CHECK (
        declared_size_bytes > 0
    ),
    CONSTRAINT ck_document_import_attempts_actual_size CHECK (
        actual_size_bytes IS NULL OR actual_size_bytes > 0
    ),
    CONSTRAINT ck_document_import_attempts_part_size CHECK (
        part_size_bytes BETWEEN 5242880 AND 5368709120
    ),
    CONSTRAINT ck_document_import_attempts_part_count CHECK (
        part_count BETWEEN 1 AND 10000
    ),
    CONSTRAINT ck_document_import_attempts_verifying_shape CHECK (
        status <> 'verifying' OR actual_size_bytes IS NOT NULL
    ),
    CONSTRAINT ck_document_import_attempts_terminal_shape CHECK (
        (status IN ('uploading','verifying') AND finished_at IS NULL) OR
        (status IN ('ready','failed','cancelled','expired') AND finished_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_document_import_attempts_status_expires
    ON document_import_attempts (status, expires_at);
CREATE INDEX IF NOT EXISTS ix_document_import_attempts_stale
    ON document_import_attempts (status, lease_expires_at);

CREATE TABLE IF NOT EXISTS document_artifacts (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    kind VARCHAR(24) NOT NULL,
    bucket VARCHAR(128) NOT NULL,
    object_key TEXT NOT NULL,
    content_type VARCHAR(128) NOT NULL,
    size_bytes BIGINT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'ready',
    artifact_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_document_artifacts_kind UNIQUE (document_id, kind),
    CONSTRAINT uq_document_artifacts_object UNIQUE (bucket, object_key),
    CONSTRAINT ck_document_artifacts_kind CHECK (kind IN ('original','normalized')),
    CONSTRAINT ck_document_artifacts_status CHECK (
        status IN ('ready','deleting','deleted')
    ),
    CONSTRAINT ck_document_artifacts_size CHECK (size_bytes > 0),
    CONSTRAINT ck_document_artifacts_sha256_length CHECK (length(sha256) = 64),
    CONSTRAINT ck_document_artifacts_deleted_shape CHECK (
        (status = 'deleted' AND deleted_at IS NOT NULL) OR
        (status <> 'deleted' AND deleted_at IS NULL)
    )
);

DROP INDEX IF EXISTS ix_document_artifacts_expires;
ALTER TABLE document_artifacts DROP COLUMN IF EXISTS expires_at;

CREATE TABLE IF NOT EXISTS artifacts (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES download_jobs (id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL,
    bucket VARCHAR(128) NOT NULL,
    object_key TEXT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL,
    duration_ms INTEGER NOT NULL,
    container VARCHAR(16) NOT NULL,
    content_type VARCHAR(128) NOT NULL,
    media_metadata JSONB NOT NULL,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_artifacts_job UNIQUE (job_id),
    CONSTRAINT uq_artifacts_object UNIQUE (bucket, object_key),
    CONSTRAINT ck_artifacts_attempt CHECK (attempt > 0),
    CONSTRAINT ck_artifacts_size CHECK (size_bytes > 0),
    CONSTRAINT ck_artifacts_duration CHECK (duration_ms > 0),
    CONSTRAINT ck_artifacts_sha256_length CHECK (length(sha256) = 64)
);

DROP INDEX IF EXISTS ix_artifacts_expires;
ALTER TABLE artifacts DROP COLUMN IF EXISTS expires_at;

CREATE TABLE IF NOT EXISTS analysis_jobs (
    id UUID PRIMARY KEY,
    input_kind VARCHAR(24) NOT NULL DEFAULT 'video',
    result_contract VARCHAR(32) NOT NULL DEFAULT 'video-visual-analysis',
    artifact_id UUID,
    document_id UUID CONSTRAINT fk_analysis_jobs_document
        REFERENCES documents (id) ON DELETE RESTRICT,
    owner_hash VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    input_sha256 VARCHAR(64) NOT NULL,
    skill_id VARCHAR(128) NOT NULL,
    skill_instructions TEXT NOT NULL,
    skill_instructions_sha256 VARCHAR(64) NOT NULL,
    output_language VARCHAR(35) NOT NULL,
    custom_prompt TEXT,
    status VARCHAR(24) NOT NULL DEFAULT 'queued',
    stage VARCHAR(24),
    stage_rank INTEGER NOT NULL DEFAULT 0,
    progress INTEGER NOT NULL DEFAULT 0,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    version INTEGER NOT NULL DEFAULT 0,
    active_run_id UUID,
    current_run_no INTEGER NOT NULL DEFAULT 1,
    current_run_trigger VARCHAR(24) NOT NULL DEFAULT 'initial',
    current_report_id UUID,
    lease_owner VARCHAR(128),
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    retry_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_code VARCHAR(64),
    error_message VARCHAR(512),
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_analysis_jobs_owner_idempotency
        UNIQUE (owner_hash, idempotency_key),
    CONSTRAINT ck_analysis_jobs_status CHECK (
        status IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed', 'cancelled')
    ),
    CONSTRAINT ck_analysis_jobs_progress CHECK (progress BETWEEN 0 AND 100),
    CONSTRAINT ck_analysis_jobs_attempt CHECK (attempt >= 0),
    CONSTRAINT ck_analysis_jobs_max_attempts CHECK (max_attempts > 0),
    CONSTRAINT ck_analysis_jobs_version CHECK (version >= 0),
    CONSTRAINT ck_analysis_jobs_run_no CHECK (current_run_no > 0),
    CONSTRAINT ck_analysis_jobs_stage_rank CHECK (stage_rank BETWEEN 0 AND 4),
    CONSTRAINT ck_analysis_jobs_sha256_length CHECK (length(input_sha256) = 64),
    CONSTRAINT ck_analysis_jobs_skill_instructions_sha256 CHECK (
        skill_instructions_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_analysis_jobs_input_kind CHECK (
        input_kind IN ('video', 'screenplay')
    ),
    CONSTRAINT ck_analysis_jobs_result_contract CHECK (
        result_contract IN (
            'video-visual-analysis', 'video-article', 'screenplay-analysis', 'screenplay-rewrite'
        )
    ),
    CONSTRAINT ck_analysis_jobs_input_shape CHECK (
        (
            input_kind = 'video'
            AND artifact_id IS NOT NULL
            AND document_id IS NULL
            AND result_contract IN ('video-visual-analysis', 'video-article')
        ) OR (
            input_kind = 'screenplay'
            AND artifact_id IS NULL
            AND document_id IS NOT NULL
            AND result_contract IN ('screenplay-analysis', 'screenplay-rewrite')
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_analysis_jobs_owner_created
    ON analysis_jobs (owner_hash, created_at);
CREATE INDEX IF NOT EXISTS ix_analysis_jobs_claim ON analysis_jobs (status, retry_at);
CREATE INDEX IF NOT EXISTS ix_analysis_jobs_stale ON analysis_jobs (status, lease_expires_at);
CREATE INDEX IF NOT EXISTS ix_analysis_jobs_queued_recovery
    ON analysis_jobs (status, updated_at);
CREATE INDEX IF NOT EXISTS ix_analysis_jobs_artifact ON analysis_jobs (artifact_id);

ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS input_kind VARCHAR(24);
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS result_contract VARCHAR(32);
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS document_id UUID;
ALTER TABLE analysis_jobs DROP CONSTRAINT IF EXISTS fk_analysis_jobs_document;
ALTER TABLE analysis_jobs ADD CONSTRAINT fk_analysis_jobs_document
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE RESTRICT;
CREATE INDEX IF NOT EXISTS ix_analysis_jobs_document ON analysis_jobs (document_id);
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS active_run_id UUID;
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS current_run_no INTEGER NOT NULL DEFAULT 1;
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS current_run_trigger VARCHAR(24) NOT NULL DEFAULT 'initial';
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS current_report_id UUID;
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS skill_id VARCHAR(128);
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS skill_instructions TEXT;
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS skill_instructions_sha256 VARCHAR(64);
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS custom_prompt TEXT;
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE analysis_jobs DROP COLUMN IF EXISTS retry_available_until;
UPDATE analysis_jobs SET
    input_kind = COALESCE(input_kind, 'video'),
    result_contract = COALESCE(result_contract, 'video-visual-analysis');
ALTER TABLE analysis_jobs ALTER COLUMN input_kind SET DEFAULT 'video';
ALTER TABLE analysis_jobs ALTER COLUMN result_contract
    SET DEFAULT 'video-visual-analysis';
ALTER TABLE analysis_jobs ALTER COLUMN input_kind SET NOT NULL;
ALTER TABLE analysis_jobs ALTER COLUMN result_contract SET NOT NULL;
ALTER TABLE analysis_jobs ALTER COLUMN artifact_id DROP NOT NULL;
ALTER TABLE analysis_jobs DROP CONSTRAINT IF EXISTS ck_analysis_jobs_input_kind;
ALTER TABLE analysis_jobs ADD CONSTRAINT ck_analysis_jobs_input_kind
    CHECK (input_kind IN ('video', 'screenplay'));
ALTER TABLE analysis_jobs
    DROP CONSTRAINT IF EXISTS ck_analysis_jobs_result_contract;
ALTER TABLE analysis_jobs ADD CONSTRAINT ck_analysis_jobs_result_contract
    CHECK (result_contract IN (
        'video-visual-analysis', 'video-article', 'screenplay-analysis', 'screenplay-rewrite'
    ));
ALTER TABLE analysis_jobs DROP CONSTRAINT IF EXISTS ck_analysis_jobs_input_shape;
ALTER TABLE analysis_jobs ADD CONSTRAINT ck_analysis_jobs_input_shape CHECK (
    (
        input_kind = 'video'
        AND artifact_id IS NOT NULL
        AND document_id IS NULL
        AND result_contract IN ('video-visual-analysis', 'video-article')
    ) OR (
        input_kind = 'screenplay'
        AND artifact_id IS NULL
        AND document_id IS NOT NULL
        AND result_contract IN ('screenplay-analysis', 'screenplay-rewrite')
    )
);
UPDATE analysis_jobs SET
    skill_id = COALESCE(skill_id, 'director-breakdown'),
    skill_instructions = COALESCE(
        skill_instructions,
        '对完整视频执行连续分镜、高光与视觉资产分析。'
    )
WHERE skill_id IS NULL OR skill_instructions IS NULL;
ALTER TABLE analysis_jobs ALTER COLUMN skill_id SET NOT NULL;
ALTER TABLE analysis_jobs ALTER COLUMN skill_instructions SET NOT NULL;
UPDATE analysis_jobs SET skill_instructions_sha256 = encode(
    digest(skill_instructions, 'sha256'), 'hex'
) WHERE skill_instructions_sha256 IS NULL;
ALTER TABLE analysis_jobs ALTER COLUMN skill_instructions_sha256 SET NOT NULL;
ALTER TABLE analysis_jobs
    DROP CONSTRAINT IF EXISTS ck_analysis_jobs_skill_instructions_sha256;
ALTER TABLE analysis_jobs ADD CONSTRAINT ck_analysis_jobs_skill_instructions_sha256
    CHECK (skill_instructions_sha256 ~ '^[0-9a-f]{64}$');
ALTER TABLE analysis_jobs DROP COLUMN IF EXISTS profile;
ALTER TABLE analysis_jobs DROP COLUMN IF EXISTS schema_version;
ALTER TABLE analysis_jobs DROP CONSTRAINT IF EXISTS ck_analysis_jobs_stage_rank;
ALTER TABLE analysis_jobs ADD CONSTRAINT ck_analysis_jobs_stage_rank
    CHECK (stage_rank BETWEEN 0 AND 4);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES analysis_jobs (id) ON DELETE CASCADE,
    run_no INTEGER NOT NULL,
    trigger VARCHAR(24) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'queued',
    stage VARCHAR(24),
    stage_rank INTEGER NOT NULL DEFAULT 0,
    progress INTEGER NOT NULL DEFAULT 0,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    version INTEGER NOT NULL DEFAULT 0,
    lease_owner VARCHAR(128),
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    retry_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_code VARCHAR(64),
    error_message VARCHAR(512),
    provider VARCHAR(32),
    model VARCHAR(128),
    cli_version VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_analysis_runs_job_no UNIQUE (job_id, run_no),
    CONSTRAINT ck_analysis_runs_trigger CHECK (
        trigger IN ('initial', 'manual_retry', 'manual_rerun')
    ),
    CONSTRAINT ck_analysis_runs_status CHECK (
        status IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed', 'cancelled')
    ),
    CONSTRAINT ck_analysis_runs_progress CHECK (progress BETWEEN 0 AND 100),
    CONSTRAINT ck_analysis_runs_attempt CHECK (attempt >= 0),
    CONSTRAINT ck_analysis_runs_max_attempts CHECK (max_attempts > 0),
    CONSTRAINT ck_analysis_runs_version CHECK (version >= 0),
    CONSTRAINT ck_analysis_runs_stage_rank CHECK (stage_rank BETWEEN 0 AND 4)
);

CREATE INDEX IF NOT EXISTS ix_analysis_runs_job_created
    ON analysis_runs (job_id, created_at);
CREATE INDEX IF NOT EXISTS ix_analysis_runs_claim ON analysis_runs (status, retry_at);
CREATE INDEX IF NOT EXISTS ix_analysis_runs_stale ON analysis_runs (status, lease_expires_at);

ALTER TABLE analysis_runs DROP CONSTRAINT IF EXISTS ck_analysis_runs_stage_rank;
ALTER TABLE analysis_runs ADD CONSTRAINT ck_analysis_runs_stage_rank
    CHECK (stage_rank BETWEEN 0 AND 4);

INSERT INTO analysis_runs (
    id, job_id, run_no, trigger, status, stage, stage_rank, progress,
    attempt, max_attempts, version, lease_owner, lease_expires_at,
    heartbeat_at, started_at, retry_at, cancel_requested_at, finished_at,
    error_code, error_message, created_at, updated_at
)
SELECT
    id, id, 1, 'initial', status, stage, stage_rank, progress,
    attempt, max_attempts, version, lease_owner, lease_expires_at,
    heartbeat_at, started_at, retry_at, cancel_requested_at, finished_at,
    error_code, error_message, created_at, updated_at
FROM analysis_jobs
ON CONFLICT (job_id, run_no) DO NOTHING;

UPDATE analysis_jobs SET active_run_id = id WHERE active_run_id IS NULL;
ALTER TABLE analysis_jobs ALTER COLUMN active_run_id SET NOT NULL;

CREATE TABLE IF NOT EXISTS analysis_retry_operations (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES analysis_jobs (id) ON DELETE CASCADE,
    run_id UUID NOT NULL REFERENCES analysis_runs (id) ON DELETE CASCADE,
    operation VARCHAR(32) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_analysis_retry_operations_key
        UNIQUE (job_id, operation, idempotency_key)
);

-- Model-call journal for SkillWorkflow resume. A row left in 'started' means a
-- call may have reached the provider; it is never re-sent automatically.
CREATE TABLE IF NOT EXISTS analysis_step_results (
    run_id UUID NOT NULL REFERENCES analysis_runs (id) ON DELETE CASCADE,
    step_key VARCHAR(64) NOT NULL,
    input_sha256 VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    payload JSONB,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (run_id, step_key),
    CONSTRAINT ck_analysis_step_results_status CHECK (status IN ('started', 'succeeded')),
    CONSTRAINT ck_analysis_step_results_input_sha CHECK (length(input_sha256) = 64),
    CONSTRAINT ck_analysis_step_results_payload CHECK (
        (status = 'succeeded') = (payload IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS analysis_report_versions (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES analysis_jobs (id) ON DELETE CASCADE,
    run_id UUID NOT NULL REFERENCES analysis_runs (id) ON DELETE CASCADE,
    input_sha256 VARCHAR(64) NOT NULL,
    language VARCHAR(35) NOT NULL,
    result_json JSONB NOT NULL,
    report_markdown TEXT NOT NULL,
    content_sha256 VARCHAR(64) NOT NULL,
    renderer_version VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    model VARCHAR(128) NOT NULL,
    cli_version VARCHAR(128) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'validated',
    attempt INTEGER NOT NULL DEFAULT 0,
    lease_owner VARCHAR(128),
    lease_expires_at TIMESTAMPTZ,
    error_message VARCHAR(512),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMPTZ,
    CONSTRAINT uq_analysis_report_versions_run UNIQUE (run_id),
    CONSTRAINT ck_analysis_report_versions_status CHECK (
        status IN (
            'validated', 'publishing', 'available', 'publish_failed',
            'delete_pending', 'deleted'
        )
    ),
    CONSTRAINT ck_analysis_report_versions_input_sha CHECK (length(input_sha256) = 64),
    CONSTRAINT ck_analysis_report_versions_content_sha CHECK (length(content_sha256) = 64),
    CONSTRAINT ck_analysis_report_versions_attempt CHECK (attempt >= 0),
    CONSTRAINT ck_analysis_report_versions_json_object CHECK (jsonb_typeof(result_json) = 'object'),
    CONSTRAINT ck_analysis_report_versions_result_kind CHECK (
        result_json ? 'kind' AND result_json ->> 'kind' IN (
            'video_visual_analysis', 'video_article',
            'screenplay_analysis', 'screenplay_rewrite'
        )
    )
);

CREATE TABLE IF NOT EXISTS analysis_report_artifacts (
    id UUID PRIMARY KEY,
    report_id UUID NOT NULL REFERENCES analysis_report_versions (id) ON DELETE CASCADE,
    format VARCHAR(16) NOT NULL,
    bucket VARCHAR(128) NOT NULL,
    object_key VARCHAR(512) NOT NULL,
    content_type VARCHAR(128) NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'available',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ,
    CONSTRAINT uq_analysis_report_artifacts_format UNIQUE (report_id, format),
    CONSTRAINT uq_analysis_report_artifacts_object UNIQUE (bucket, object_key),
    CONSTRAINT ck_analysis_report_artifacts_format CHECK (format IN ('markdown', 'docx')),
    CONSTRAINT ck_analysis_report_artifacts_status CHECK (
        status IN ('available', 'delete_pending', 'deleted', 'failed')
    ),
    CONSTRAINT ck_analysis_report_artifacts_size CHECK (size_bytes > 0),
    CONSTRAINT ck_analysis_report_artifacts_sha CHECK (length(sha256) = 64)
);

ALTER TABLE analysis_report_versions
    DROP CONSTRAINT IF EXISTS ck_analysis_report_versions_status;
ALTER TABLE analysis_report_versions
    ADD CONSTRAINT ck_analysis_report_versions_status CHECK (
        status IN (
            'validated', 'publishing', 'available', 'publish_failed',
            'delete_pending', 'deleted'
        )
    );

UPDATE analysis_report_versions AS report
SET result_json = jsonb_set(
    report.result_json,
    '{kind}',
    to_jsonb('video_visual_analysis'::text),
    true
)
FROM analysis_jobs AS job
WHERE report.job_id = job.id
  AND job.result_contract = 'video-visual-analysis'
  AND NOT report.result_json ? 'kind';

ALTER TABLE analysis_report_versions
    DROP CONSTRAINT IF EXISTS ck_analysis_report_versions_result_kind;
ALTER TABLE analysis_report_versions
    ADD CONSTRAINT ck_analysis_report_versions_result_kind CHECK (
        result_json ? 'kind' AND result_json ->> 'kind' IN (
            'video_visual_analysis', 'video_article',
            'screenplay_analysis', 'screenplay_rewrite'
        )
    );
ALTER TABLE analysis_report_artifacts DROP COLUMN IF EXISTS expires_at;

-- Legacy releases could mark a job succeeded before the durable Markdown and
-- DOCX report existed. Fail those inconsistent projections closed so clients
-- can retry instead of receiving a false success without downloadable output.
UPDATE analysis_jobs
SET
    status = 'failed',
    stage = NULL,
    stage_rank = 0,
    version = version + 1,
    error_code = 'analysis_report_unavailable',
    error_message = 'durable analysis report is unavailable',
    finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP),
    updated_at = CURRENT_TIMESTAMP
WHERE status = 'succeeded' AND current_report_id IS NULL;

UPDATE analysis_runs AS run
SET
    status = analysis.status,
    stage = analysis.stage,
    stage_rank = analysis.stage_rank,
    progress = analysis.progress,
    attempt = analysis.attempt,
    max_attempts = analysis.max_attempts,
    version = analysis.version,
    finished_at = analysis.finished_at,
    error_code = analysis.error_code,
    error_message = analysis.error_message,
    updated_at = analysis.updated_at
FROM analysis_jobs AS analysis
WHERE run.id = analysis.active_run_id
  AND run.status = 'succeeded'
  AND analysis.status = 'failed'
  AND analysis.error_code = 'analysis_report_unavailable';

ALTER TABLE analysis_jobs
    DROP CONSTRAINT IF EXISTS ck_analysis_jobs_succeeded_report;
ALTER TABLE analysis_jobs
    ADD CONSTRAINT ck_analysis_jobs_succeeded_report CHECK (
        status <> 'succeeded' OR current_report_id IS NOT NULL
    );

CREATE TABLE IF NOT EXISTS analysis_artifact_locks (
    job_id UUID PRIMARY KEY
        REFERENCES analysis_jobs (id) ON DELETE CASCADE,
    artifact_id UUID NOT NULL
        REFERENCES artifacts (id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_analysis_artifact_locks_artifact
    ON analysis_artifact_locks (artifact_id);

CREATE TABLE IF NOT EXISTS analysis_document_locks (
    job_id UUID PRIMARY KEY
        REFERENCES analysis_jobs (id) ON DELETE CASCADE,
    document_id UUID NOT NULL
        REFERENCES documents (id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_analysis_document_locks_document
    ON analysis_document_locks (document_id);

CREATE TABLE IF NOT EXISTS analysis_worker_heartbeats (
    worker_id VARCHAR(128) PRIMARY KEY,
    app_version VARCHAR(128) NOT NULL,
    message_schema_version INTEGER NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_analysis_worker_heartbeats_schema_version CHECK (
        message_schema_version > 0
    )
);

CREATE INDEX IF NOT EXISTS ix_analysis_worker_heartbeats_last_seen
    ON analysis_worker_heartbeats (last_seen_at);

CREATE TABLE IF NOT EXISTS outbox_events (
    id UUID PRIMARY KEY,
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_id UUID NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    payload JSONB NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    publish_attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    last_error TEXT,
    lock_owner VARCHAR(128),
    lock_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_outbox_publish_attempts CHECK (publish_attempts >= 0)
);

CREATE INDEX IF NOT EXISTS ix_outbox_events_publishable
    ON outbox_events (published_at, available_at, next_attempt_at);
CREATE INDEX IF NOT EXISTS ix_outbox_events_lock ON outbox_events (lock_expires_at);

ALTER TABLE outbox_events ADD COLUMN IF NOT EXISTS aggregate_version INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS uq_outbox_aggregate_event_version
    ON outbox_events (aggregate_type, aggregate_id, event_type, aggregate_version);
ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS ck_outbox_intent_version;
ALTER TABLE outbox_events ADD CONSTRAINT ck_outbox_intent_version
    CHECK (aggregate_type <> 'download_intent' OR aggregate_version IS NOT NULL);

CREATE TABLE IF NOT EXISTS download_intents (
    id UUID PRIMARY KEY,
    owner_hash VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    url_ciphertext BYTEA NOT NULL,
    url_nonce BYTEA NOT NULL,
    url_key_id VARCHAR(64) NOT NULL,
    mode VARCHAR(16) NOT NULL DEFAULT 'inspect',
    access_policy VARCHAR(32) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'queued',
    version INTEGER NOT NULL DEFAULT 0,
    fence INTEGER NOT NULL DEFAULT 0,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    remaining_budget_ms INTEGER NOT NULL DEFAULT 180000,
    deadline TIMESTAMPTZ NOT NULL,
    generation INTEGER NOT NULL DEFAULT 0,
    operation_id VARCHAR(128),
    retry_at TIMESTAMPTZ,
    authorization_id UUID,
    authorization_deadline TIMESTAMPTZ,
    inspection_id UUID REFERENCES media_inspections (id),
    job_id UUID REFERENCES download_jobs (id),
    reason_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_download_intents_owner_key UNIQUE (owner_hash, idempotency_key),
    CONSTRAINT uq_download_intents_job UNIQUE (job_id),
    CONSTRAINT ck_download_intents_status CHECK (status IN (
        'queued','preparing','resolving','retry_wait','action_required',
        'ready','handed_off','cancelled','expired','failed'
    )),
    CONSTRAINT ck_download_intents_mode CHECK (mode = 'inspect'),
    CONSTRAINT ck_download_intents_policy CHECK (access_policy IN (
        'public','public_session','operator_public','personal_entitled'
    )),
    CONSTRAINT ck_download_intents_version CHECK (version >= 0 AND fence >= 0),
    CONSTRAINT ck_download_intents_attempt CHECK (
        attempt >= 0 AND attempt <= max_attempts AND max_attempts BETWEEN 1 AND 3
    ),
    CONSTRAINT ck_download_intents_budget CHECK (remaining_budget_ms BETWEEN 0 AND 180000),
    CONSTRAINT ck_download_intents_generation CHECK (generation >= 0),
    CONSTRAINT ck_download_intents_operation CHECK (
        (status IN ('preparing','resolving')) = (operation_id IS NOT NULL)
    ),
    CONSTRAINT ck_download_intents_retry CHECK ((status = 'retry_wait') = (retry_at IS NOT NULL)),
    CONSTRAINT ck_download_intents_result CHECK (status <> 'ready' OR inspection_id IS NOT NULL),
    CONSTRAINT ck_download_intents_handoff CHECK (status <> 'handed_off' OR job_id IS NOT NULL),
    CONSTRAINT ck_download_intents_action CHECK (
        status <> 'action_required' OR (authorization_id IS NOT NULL AND authorization_deadline IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS ix_download_intents_owner_created
    ON download_intents (owner_hash, created_at);
-- Cut over only after the old intent consumer is drained. Never erase in-flight work.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = 'download_intents'
               AND column_name = 'lease_owner')
       AND EXISTS (SELECT 1 FROM download_intents
                   WHERE status IN ('queued','preparing','resolving','retry_wait','action_required')) THEN
        RAISE EXCEPTION 'drain intent executions before Temporal cutover';
    END IF;
END $$;
ALTER TABLE download_intents ADD COLUMN IF NOT EXISTS generation INTEGER NOT NULL DEFAULT 0;
ALTER TABLE download_intents ADD COLUMN IF NOT EXISTS operation_id VARCHAR(128);
ALTER TABLE download_intents DROP COLUMN IF EXISTS lease_owner;
ALTER TABLE download_intents DROP COLUMN IF EXISTS lease_expires_at;
DROP INDEX IF EXISTS ix_download_intents_recovery;
ALTER TABLE download_intents DROP CONSTRAINT IF EXISTS ck_download_intents_operation;
ALTER TABLE download_intents ADD CONSTRAINT ck_download_intents_operation CHECK (
    (status IN ('preparing','resolving')) = (operation_id IS NOT NULL)
);
ALTER TABLE download_intents DROP CONSTRAINT IF EXISTS ck_download_intents_generation;
ALTER TABLE download_intents ADD CONSTRAINT ck_download_intents_generation CHECK (generation >= 0);
CREATE INDEX IF NOT EXISTS ix_download_intents_deadline
    ON download_intents (status, deadline);
CREATE UNIQUE INDEX IF NOT EXISTS uq_download_intents_inspection
    ON download_intents (inspection_id);

CREATE TABLE IF NOT EXISTS rabbitmq_dlq_replays (
    id UUID PRIMARY KEY,
    source_queue VARCHAR(64) NOT NULL,
    original_event_id UUID NOT NULL,
    replay_event_id UUID NOT NULL UNIQUE,
    replay_count INTEGER NOT NULL,
    actor VARCHAR(128) NOT NULL,
    reason VARCHAR(256) NOT NULL,
    status VARCHAR(24) NOT NULL,
    error_code VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_rabbitmq_dlq_replay_attempt
        UNIQUE (source_queue, original_event_id, replay_count),
    CONSTRAINT ck_rabbitmq_dlq_replay_queue CHECK (
        source_queue IN (
            'video.download.dead',
            'video.analysis.dead',
            'video.analysis-report.dead',
            'video.import.dead'
        )
    ),
    CONSTRAINT ck_rabbitmq_dlq_replay_status CHECK (
        status IN ('pending', 'published', 'failed')
    ),
    CONSTRAINT ck_rabbitmq_dlq_replay_count CHECK (replay_count BETWEEN 1 AND 3)
);

ALTER TABLE rabbitmq_dlq_replays
    DROP CONSTRAINT IF EXISTS ck_rabbitmq_dlq_replay_queue;
ALTER TABLE rabbitmq_dlq_replays
    ADD CONSTRAINT ck_rabbitmq_dlq_replay_queue CHECK (
        source_queue IN (
            'video.download.dead',
            'video.analysis.dead',
            'video.analysis-report.dead',
            'video.import.dead'
        )
    );

CREATE TABLE IF NOT EXISTS operational_counters (
    metric VARCHAR(64) NOT NULL,
    dimension VARCHAR(64) NOT NULL,
    value BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (metric, dimension),
    CONSTRAINT ck_operational_counters_value CHECK (value >= 0)
);

CREATE TABLE IF NOT EXISTS provider_route_cooldowns (
    provider_key VARCHAR(32) NOT NULL,
    access_policy_id VARCHAR(32) NOT NULL,
    egress_binding_id VARCHAR(128) NOT NULL,
    blocked_until TIMESTAMPTZ,
    reason_code VARCHAR(32) NOT NULL,
    stable_error_code VARCHAR(128),
    probe_owner VARCHAR(64),
    probe_lease_until TIMESTAMPTZ,
    failure_count INTEGER NOT NULL DEFAULT 0,
    success_streak INTEGER NOT NULL DEFAULT 0,
    version BIGINT NOT NULL,
    PRIMARY KEY (provider_key, access_policy_id, egress_binding_id),
    CONSTRAINT ck_provider_route_cooldown_version CHECK (version > 0),
    CONSTRAINT ck_provider_route_cooldown_policy CHECK (
        access_policy_id IN ('public','operator_public','personal_entitled')
    ),
    CONSTRAINT ck_provider_route_cooldown_probe CHECK (
        (probe_owner IS NULL) = (probe_lease_until IS NULL)
        AND (probe_owner IS NULL OR blocked_until IS NOT NULL)
    ),
    CONSTRAINT ck_provider_route_cooldown_failures CHECK (failure_count >= 0),
    CONSTRAINT ck_provider_route_cooldown_successes CHECK (success_streak >= 0)
);

ALTER TABLE provider_route_cooldowns
    ADD COLUMN IF NOT EXISTS stable_error_code VARCHAR(128),
    ADD COLUMN IF NOT EXISTS failure_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS success_streak INTEGER NOT NULL DEFAULT 0;
ALTER TABLE provider_route_cooldowns
    DROP CONSTRAINT IF EXISTS ck_provider_route_cooldown_reason;

CREATE TABLE IF NOT EXISTS provider_canary_results (
    id UUID PRIMARY KEY,
    target_id VARCHAR(128) NOT NULL,
    provider_key VARCHAR(32) NOT NULL,
    profile_version VARCHAR(128) NOT NULL,
    stage VARCHAR(16) NOT NULL,
    access_mode VARCHAR(24) NOT NULL,
    outcome VARCHAR(16) NOT NULL,
    stable_error_code VARCHAR(128),
    checked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duration_ms INTEGER NOT NULL,
    engine_commit VARCHAR(128) NOT NULL,
    egress_affinity_id VARCHAR(128) NOT NULL,
    client_profile_id VARCHAR(128) NOT NULL,
    context_generation_id VARCHAR(64) NOT NULL,
    CONSTRAINT ck_provider_canary_stage CHECK (
        stage IN ('metadata', 'media', 'analysis')
    ),
    CONSTRAINT ck_provider_canary_access_mode CHECK (
        access_mode IN ('anonymous', 'guest', 'operator_managed')
    ),
    CONSTRAINT ck_provider_canary_outcome CHECK (
        outcome IN ('succeeded', 'failed')
    ),
    CONSTRAINT ck_provider_canary_duration CHECK (duration_ms >= 0),
    CONSTRAINT ck_provider_canary_error CHECK (
        (outcome = 'failed') = (stable_error_code IS NOT NULL)
    )
);

ALTER TABLE provider_canary_results
    DROP CONSTRAINT IF EXISTS ck_provider_canary_access_mode;
ALTER TABLE provider_canary_results
    ADD CONSTRAINT ck_provider_canary_access_mode CHECK (
        access_mode IN ('anonymous', 'guest', 'operator_managed')
    );

ALTER TABLE provider_canary_results
    DROP CONSTRAINT IF EXISTS ck_provider_canary_stage;
ALTER TABLE provider_canary_results
    ADD CONSTRAINT ck_provider_canary_stage CHECK (
        stage IN ('metadata', 'media', 'analysis')
    );

ALTER TABLE provider_canary_results
    ADD COLUMN IF NOT EXISTS context_generation_id VARCHAR(64);
UPDATE provider_canary_results
SET context_generation_id = 'legacy'
WHERE context_generation_id IS NULL;
ALTER TABLE provider_canary_results
    ALTER COLUMN context_generation_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_provider_canary_provider_checked
    ON provider_canary_results (provider_key, checked_at);
DROP INDEX IF EXISTS ix_provider_canary_target_checked;
DROP INDEX IF EXISTS ix_provider_canary_target_route_checked;
DROP INDEX IF EXISTS ix_provider_canary_target_profile_route_checked;
CREATE INDEX IF NOT EXISTS ix_provider_canary_target_generation_checked
    ON provider_canary_results (
        target_id, profile_version, stage, access_mode,
        context_generation_id, checked_at
    );

CREATE TABLE IF NOT EXISTS task_events (
    id UUID PRIMARY KEY,
    owner_hash VARCHAR(64) NOT NULL,
    task_type VARCHAR(16) NOT NULL,
    task_id UUID NOT NULL,
    run_id UUID,
    run_no INTEGER,
    version INTEGER NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_task_events_version UNIQUE (task_type, task_id, version),
    CONSTRAINT ck_task_events_type CHECK (task_type IN ('download', 'analysis')),
    CONSTRAINT ck_task_events_version CHECK (version >= 0),
    CONSTRAINT ck_task_events_payload_object CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX IF NOT EXISTS ix_task_events_owner_task
    ON task_events (owner_hash, task_type, task_id, version);
CREATE INDEX IF NOT EXISTS ix_task_events_occurred ON task_events (occurred_at);

CREATE OR REPLACE FUNCTION emit_download_task_event() RETURNS trigger AS $$
DECLARE
    event_uuid UUID := gen_random_uuid();
    public_payload JSONB;
BEGIN
    public_payload := jsonb_strip_nulls(jsonb_build_object(
        'task_type', 'download', 'task_id', NEW.id::text,
        'version', NEW.version, 'status', NEW.status, 'stage', NEW.stage,
        'progress', NEW.progress, 'attempt', NEW.attempt,
        'error', CASE WHEN NEW.error_code IS NULL THEN NULL
            ELSE jsonb_build_object('code', NEW.error_code) END,
        'occurred_at', NEW.updated_at
    ));
    INSERT INTO task_events (
        id, owner_hash, task_type, task_id, version, event_type, payload, occurred_at
    ) VALUES (
        event_uuid, NEW.owner_hash, 'download', NEW.id, NEW.version,
        'task.updated', public_payload, NEW.updated_at
    );
    INSERT INTO outbox_events (
        id, aggregate_type, aggregate_id, event_type, payload, available_at, created_at
    ) VALUES (
        event_uuid, 'task', NEW.id, 'task.state.changed', public_payload,
        NEW.updated_at, NEW.updated_at
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION emit_analysis_task_event() RETURNS trigger AS $$
DECLARE
    event_uuid UUID := gen_random_uuid();
    report_state VARCHAR(24);
    public_payload JSONB;
BEGIN
    SELECT status INTO report_state FROM analysis_report_versions
        WHERE job_id = NEW.id ORDER BY created_at DESC LIMIT 1;
    public_payload := jsonb_strip_nulls(jsonb_build_object(
        'task_type', 'analysis', 'task_id', NEW.id::text,
        'run_id', NEW.active_run_id::text, 'run_no', NEW.current_run_no,
        'version', NEW.version, 'status', NEW.status, 'stage', NEW.stage,
        'progress', NEW.progress, 'attempt', NEW.attempt,
        'report_status', report_state,
        'error', CASE WHEN NEW.error_code IS NULL THEN NULL
            ELSE jsonb_build_object('code', NEW.error_code) END,
        'occurred_at', NEW.updated_at
    ));
    INSERT INTO task_events (
        id, owner_hash, task_type, task_id, run_id, run_no, version,
        event_type, payload, occurred_at
    ) VALUES (
        event_uuid, NEW.owner_hash, 'analysis', NEW.id, NEW.active_run_id,
        NEW.current_run_no, NEW.version, 'task.updated', public_payload, NEW.updated_at
    );
    INSERT INTO outbox_events (
        id, aggregate_type, aggregate_id, event_type, payload, available_at, created_at
    ) VALUES (
        event_uuid, 'task', NEW.id, 'task.state.changed', public_payload,
        NEW.updated_at, NEW.updated_at
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS download_task_event_trigger ON download_jobs;
CREATE TRIGGER download_task_event_trigger
AFTER INSERT OR UPDATE OF version ON download_jobs
FOR EACH ROW EXECUTE FUNCTION emit_download_task_event();

DROP TRIGGER IF EXISTS analysis_task_event_trigger ON analysis_jobs;
CREATE TRIGGER analysis_task_event_trigger
AFTER INSERT OR UPDATE OF version ON analysis_jobs
FOR EACH ROW EXECUTE FUNCTION emit_analysis_task_event();

-- Daily usage survives resource deletion. Active and retained usage is derived
-- from resource state; no duplicate lifecycle state or mutable billing counter.
CREATE TABLE IF NOT EXISTS resource_admissions (
    id UUID PRIMARY KEY,
    owner_hash VARCHAR(64) NOT NULL,
    kind VARCHAR(24) NOT NULL,
    reserved_bytes BIGINT NOT NULL,
    analysis_attempts INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_admissions_kind CHECK (
        kind IN ('download','media_import','document_import','analysis','inspection')
    ),
    CONSTRAINT ck_admissions_bytes CHECK (reserved_bytes >= 0),
    CONSTRAINT ck_admissions_attempts CHECK (analysis_attempts >= 0)
);

ALTER TABLE resource_admissions DROP CONSTRAINT IF EXISTS ck_admissions_kind;
ALTER TABLE resource_admissions ADD CONSTRAINT ck_admissions_kind
    CHECK (kind IN ('download','media_import','document_import','analysis','inspection'));
ALTER TABLE resource_admissions DROP CONSTRAINT IF EXISTS ck_admissions_bytes;
ALTER TABLE resource_admissions ADD CONSTRAINT ck_admissions_bytes CHECK (reserved_bytes >= 0);
CREATE INDEX IF NOT EXISTS ix_admissions_owner_created
    ON resource_admissions (owner_hash, created_at);

CREATE TABLE IF NOT EXISTS email_registration_challenges (
    email varchar(320) PRIMARY KEY,
    generation uuid NOT NULL,
    code_digest varchar(64) NOT NULL,
    requested_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    sent boolean NOT NULL DEFAULT false,
    consumed boolean NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS ix_email_registration_expires ON email_registration_challenges (expires_at);

-- Retired host-side sources and authorization transactions.
DROP TABLE IF EXISTS provider_authorizations;
DROP TABLE IF EXISTS provider_session_sources;

COMMIT;

-- Request audit metadata only. No FK: deleting an account/resource retains evidence.
CREATE TABLE IF NOT EXISTS operation_logs (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    actor_id UUID,
    actor_name VARCHAR(128),
    operation VARCHAR(160) NOT NULL,
    description VARCHAR(256) NOT NULL,
    method VARCHAR(8) NOT NULL,
    route VARCHAR(256) NOT NULL,
    resource_id UUID,
    resource_key VARCHAR(128),
    outcome VARCHAR(16) NOT NULL,
    source VARCHAR(16) NOT NULL DEFAULT 'request',
    task_state VARCHAR(32),
    status_code INTEGER,
    error_code VARCHAR(128),
    CONSTRAINT ck_operation_logs_outcome CHECK (outcome IN ('started','succeeded','failed'))
);
ALTER TABLE operation_logs ADD COLUMN IF NOT EXISTS resource_key VARCHAR(128);
CREATE INDEX IF NOT EXISTS ix_operation_logs_created ON operation_logs (created_at, id);
CREATE INDEX IF NOT EXISTS ix_operation_logs_actor_created ON operation_logs (actor_id, created_at);

-- State events are inserted atomically with business transitions, not backfilled
-- from mutable current state. Progress-only updates intentionally produce no log.
CREATE OR REPLACE FUNCTION record_system_task_operation() RETURNS trigger AS $$
DECLARE
    current_row JSONB;
    state_value TEXT;
    object_id UUID;
BEGIN
    current_row := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    IF TG_OP = 'UPDATE'
       AND (to_jsonb(OLD)->>'status') IS NOT DISTINCT FROM (current_row->>'status')
       AND (to_jsonb(OLD)->>'deleted_at') IS NOT DISTINCT FROM (current_row->>'deleted_at') THEN
        RETURN NEW;
    END IF;
    state_value := CASE WHEN TG_OP = 'DELETE' OR current_row->>'deleted_at' IS NOT NULL
        THEN 'deleted' ELSE current_row->>'status' END;
    object_id := (current_row->>'id')::uuid;
    INSERT INTO operation_logs (id, created_at, finished_at, actor_name, operation, description, method, route, resource_id, outcome, source, task_state, error_code)
    VALUES (gen_random_uuid(), clock_timestamp(), clock_timestamp(), '系统', TG_TABLE_NAME || '.' || lower(TG_OP), TG_ARGV[0], 'SYSTEM', TG_TABLE_NAME, object_id,
        CASE WHEN state_value = 'failed' THEN 'failed' ELSE 'succeeded' END,
        'task', state_value, current_row->>'error_code');
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS operation_log_state_trigger ON download_intents;
CREATE TRIGGER operation_log_state_trigger AFTER INSERT OR UPDATE OR DELETE ON download_intents
FOR EACH ROW EXECUTE FUNCTION record_system_task_operation('链接解析');
DROP TRIGGER IF EXISTS operation_log_state_trigger ON download_jobs;
CREATE TRIGGER operation_log_state_trigger AFTER INSERT OR UPDATE OR DELETE ON download_jobs
FOR EACH ROW EXECUTE FUNCTION record_system_task_operation('下载任务');
DROP TRIGGER IF EXISTS operation_log_state_trigger ON analysis_jobs;
CREATE TRIGGER operation_log_state_trigger AFTER INSERT OR UPDATE OR DELETE ON analysis_jobs
FOR EACH ROW EXECUTE FUNCTION record_system_task_operation('AI 分析');
DROP TRIGGER IF EXISTS operation_log_state_trigger ON documents;
CREATE TRIGGER operation_log_state_trigger AFTER INSERT OR UPDATE OR DELETE ON documents
FOR EACH ROW EXECUTE FUNCTION record_system_task_operation('剧本文档');
DROP TRIGGER IF EXISTS operation_log_state_trigger ON media_imports;
CREATE TRIGGER operation_log_state_trigger AFTER INSERT OR UPDATE OR DELETE ON media_imports
FOR EACH ROW EXECUTE FUNCTION record_system_task_operation('视频导入');
