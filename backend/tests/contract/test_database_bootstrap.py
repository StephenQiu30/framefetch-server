from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from app.integrations.readiness import EXPECTED_DATABASE_TABLES

ROOT = Path(__file__).resolve().parents[2]
ENV_COMPOSE_PATH = ROOT.parent / "docker-compose-env.yml"
COMPOSE_PATH = ROOT.parent / "docker-compose.yml"
PROD_COMPOSE_PATH = ROOT.parent / "docker-compose-prod.yml"
ENV_EXAMPLE_PATH = ROOT.parent / ".env.example"
SCHEMA_PATH = ROOT / "sql/schema.sql"
ROOT_README_PATH = ROOT.parent / "README.md"
FRONTEND_README_PATH = ROOT.parent / "frontend/README.md"
STARTUP_SCRIPT_PATH = ROOT.parent / "scripts/restart-project.ps1"
DOCKERFILE_PATH = ROOT / "Dockerfile"


def _service_block(document: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)",
        document,
    )
    assert match is not None
    return match.group(1)


def _env_value(path: Path, name: str) -> str:
    match = re.search(
        rf"(?m)^{re.escape(name)}=(.+)$", path.read_text(encoding="utf-8")
    )
    assert match is not None
    return match.group(1)


def test_execution_context_schema_supports_new_and_existing_databases() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    create_jobs = schema.split("CREATE TABLE IF NOT EXISTS download_jobs (", 1)[
        1
    ].split(");", 1)[0]
    assert "execution_context JSONB" in create_jobs
    assert "execution_context_attempt INTEGER" in create_jobs
    assert (
        "ALTER TABLE download_jobs\n"
        "    ADD COLUMN IF NOT EXISTS execution_context JSONB;"
    ) in schema
    assert (
        "ALTER TABLE download_jobs\n"
        "    ADD COLUMN IF NOT EXISTS execution_context_attempt INTEGER;"
    ) in schema


def _assert_exact_http_origins(value: str) -> None:
    assert value
    assert "*" not in value
    assert "?" not in value
    for origin in value.split(","):
        parsed = urlsplit(origin)
        assert parsed.scheme in {"http", "https"}
        assert parsed.hostname is not None
        assert parsed.username is None
        assert parsed.password is None
        assert parsed.path == ""
        assert parsed.query == ""
        assert parsed.fragment == ""
        assert origin == f"{parsed.scheme}://{parsed.netloc}"
        _ = parsed.port


def test_environment_templates_do_not_override_duplicate_assignments() -> None:
    assignments = re.findall(
        r"(?m)^([A-Z][A-Z0-9_]*)=", ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    )
    assert len(assignments) == len(set(assignments))
    assert _env_value(ENV_EXAMPLE_PATH, "REQUEST_TIMEOUT_SECONDS") == "180"


def test_core_api_boot_does_not_wait_for_session_readiness() -> None:
    environment = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    for removed in (
        "RUNNER_OPERATOR_BASE_URLS",
        "RUNNER_DEFAULT_ACCESS_POLICIES",
        "PROVIDER_SOURCE_ENCRYPTION_KEY",
        "AUTO_BROWSER_SOURCE_PROVIDERS",
        "COMPOSE_PROFILES",
    ):
        assert removed not in environment

    for path in (COMPOSE_PATH, PROD_COMPOSE_PATH):
        services = yaml.safe_load(path.read_text(encoding="utf-8"))["services"]
        # `docker compose up` starts everything; there are no opt-in profiles.
        assert not any(config.get("profiles") for config in services.values())
        for service in ("api", "frontend", "worker"):
            assert not set(services[service].get("depends_on", {})) & set(
                ("session-runner",)
            )


def test_frontend_compose_receives_only_required_runtime_configuration() -> None:
    expected = {
        "AUTH_WEB_COOKIE_NAME",
        "BACKEND_ORIGIN",
        "HOSTNAME",
        "MINIO_ENDPOINT",
        "MINIO_INTERNAL_SECURE",
        "MINIO_PUBLIC_ENDPOINT",
        "MINIO_PUBLIC_SECURE",
        "NODE_ENV",
        "PORT",
        "SITE_URL",
        "SITE_INDEXABLE",
    }
    for path in (COMPOSE_PATH, PROD_COMPOSE_PATH):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        frontend = document["services"]["frontend"]
        api = document["services"]["api"]

        assert "env_file" not in frontend
        local_only = {"MINIO_LOCAL_BROWSER_ENDPOINT", "MINIO_LOCAL_BROWSER_SECURE"}
        assert set(frontend["environment"]) == expected | local_only
        assert (
            frontend["networks"]["app_net"]["ipv4_address"]
            == "${FRONTEND_IPV4_ADDRESS:-10.251.0.10}"
        )
        assert "${TRUSTED_PROXY_CIDRS" in api["environment"]["TRUSTED_PROXY_CIDRS"]
        assert (
            api["environment"]["TRUSTED_FRONTEND_PROXY_IP"]
            == frontend["networks"]["app_net"]["ipv4_address"]
        )


def test_production_analysis_is_opt_in() -> None:
    compose = yaml.safe_load(PROD_COMPOSE_PATH.read_text(encoding="utf-8"))
    environment = compose["services"]["api"]["environment"]
    for name in ("ANALYSIS_ENABLED", "SCREENPLAY_ANALYSIS_ENABLED"):
        assert environment[name] == "${" + name + ":-false}"


def test_current_schema_can_be_applied_repeatedly() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    table_names = set(
        re.findall(r"^CREATE TABLE IF NOT EXISTS ([a-z_]+)", schema, re.MULTILINE)
    )

    assert table_names == EXPECTED_DATABASE_TABLES
    assert not re.search(r"^CREATE TABLE (?!IF NOT EXISTS)", schema, re.MULTILINE)
    assert not re.search(r"^CREATE INDEX (?!IF NOT EXISTS)", schema, re.MULTILINE)
    assert "analysis_report_unavailable" in schema
    assert "ck_analysis_jobs_succeeded_report" in schema
    assert "ix_download_jobs_queued_recovery" in schema
    assert "ck_download_jobs_source_shape" in schema
    assert "ck_media_imports_terminal_shape" in schema
    assert "ck_media_import_attempts_verifying_shape" in schema
    assert "ck_media_import_attempts_terminal_shape" in schema
    assert "ck_documents_ready_shape" in schema
    assert "ck_document_import_attempts_terminal_shape" in schema
    assert "ck_document_artifacts_deleted_shape" in schema
    assert "fk_analysis_jobs_document" in schema
    assert "ck_analysis_jobs_input_shape" in schema
    assert "SET source_kind = 'remote_provider'" in schema
    assert "result_contract = COALESCE(" in schema
    assert "ck_analysis_report_versions_result_kind" in schema
    assert "result_json ? 'kind'" in schema
    assert schema.count("'video_article'") >= 2
    assert "to_jsonb('video_visual_analysis'::text)" in schema
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in schema
    assert "skill_instructions_sha256" in schema
    assert "digest(skill_instructions, 'sha256')" in schema
    assert "ck_analysis_jobs_skill_instructions_sha256" in schema
    assert "ALTER TABLE artifacts DROP COLUMN IF EXISTS expires_at" in schema
    assert "ALTER TABLE documents DROP COLUMN IF EXISTS expires_at" in schema
    assert "ALTER TABLE document_artifacts DROP COLUMN IF EXISTS expires_at" in schema
    assert (
        "ALTER TABLE analysis_report_artifacts DROP COLUMN IF EXISTS expires_at"
        in schema
    )
    assert (
        "ALTER TABLE analysis_jobs DROP COLUMN IF EXISTS retry_available_until"
        in schema
    )
    assert "('hongguo_web', '红果短剧官方分享', 230, TRUE, FALSE)" in schema
    assert "engine IN ('codex', 'claude', 'deepseek', 'openrouter', 'openai')" in schema
    assert (
        "engine NOT IN ('deepseek', 'openrouter', 'openai') OR auth_mode = 'api_key'"
        in schema
    )
    assert "'local-codex', '本机 Codex', 'codex', 'host_login'" in schema
    assert "ck_ai_provider_local_codex_shape" in schema
    assert "ON CONFLICT (key) DO UPDATE SET" in schema
    for table in (
        "provider_canary_results",
        "provider_route_cooldowns",
        "resolution_attempts",
    ):
        assert f"DROP TABLE IF EXISTS {table};" in schema
        assert f"CREATE TABLE IF NOT EXISTS {table}" not in schema
    for column in (
        "resolution_plan",
        "next_strategy_id",
        "remaining_budget_ms",
        "fence",
        "access_policy",
    ):
        assert f"ALTER TABLE download_intents DROP COLUMN IF EXISTS {column};" in schema
    assert "ADD COLUMN IF NOT EXISTS execution_context JSONB" in schema
    assert "'video.import.dead'" in schema


def test_download_queue_contract_declares_a_dlq_binding() -> None:
    compose = ENV_COMPOSE_PATH.read_text(encoding="utf-8")

    assert "declare_queue video.download" in compose
    assert "declare_queue video.download-intent" not in compose
    assert (
        "declare_binding video.events video.download-intent download.intent.requested"
        not in compose
    )
    assert '"x-dead-letter-exchange":"video.events.dead"' in compose
    assert '"x-dead-letter-routing-key":"' in compose
    assert "'\"$$1\"'.dead" in compose
    assert (
        "declare_binding video.events.dead video.download.dead video.download.dead"
        in compose
    )


def test_ai_provider_selection_is_not_configured_by_environment() -> None:
    for path in (ENV_EXAMPLE_PATH, COMPOSE_PATH, PROD_COMPOSE_PATH):
        document = path.read_text(encoding="utf-8")
        for name in (
            "ANALYSIS_CLI_PROVIDER",
            "ANALYSIS_CODEX_MODEL",
            "ANALYSIS_CLAUDE_MODEL",
        ):
            assert name not in document


def test_compose_does_not_bundle_host_managed_infrastructure() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    for service in (
        "postgres",
        "database-init",
        "rabbitmq",
        "rabbitmq-init",
        "redis",
        "minio",
        "minio-init",
    ):
        assert not re.search(rf"(?m)^  {re.escape(service)}:$", compose)
    assert "profiles: [environment]" not in compose
    assert "/docker-entrypoint-initdb.d/" not in compose


def test_environment_bootstrap_provisions_analysis_storage_probe() -> None:
    compose = ENV_COMPOSE_PATH.read_text(encoding="utf-8")
    minio_init = _service_block(compose, "minio-init")

    assert (
        "image: minio/mc@sha256:"
        "a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727"
    ) in minio_init
    assert "mc mb --ignore-existing" in minio_init
    assert "system/analysis-readiness" in minio_init
    assert "mc pipe" in minio_init


def test_environment_minio_applies_exact_browser_cors_origins() -> None:
    compose = ENV_COMPOSE_PATH.read_text(encoding="utf-8")
    minio = _service_block(compose, "minio")

    assert (
        "image: minio/minio@sha256:"
        "14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e"
    ) in minio
    expected_setting = (
        'MINIO_API_CORS_ALLOW_ORIGIN: "${MINIO_CORS_ALLOWED_ORIGINS-'
        'http://127.0.0.1:8101,http://localhost:8101}"'
    )
    assert expected_setting in minio
    assert "entrypoint:" not in minio
    assert 'command: ["minio", "server", "/data"' in minio
    assert "/bin/sh" not in minio
    assert "/usr/bin/docker-entrypoint.sh" not in minio

    _assert_exact_http_origins(
        _env_value(ENV_EXAMPLE_PATH, "MINIO_CORS_ALLOWED_ORIGINS")
    )


def test_database_consumers_use_the_configured_postgres_service() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    expected_endpoint = (
        "@${POSTGRES_HOST:-host.docker.internal}:${POSTGRES_PORT:-5432}/"
    )

    for service in ("api", "worker"):
        service_config = _service_block(compose, service)
        assert expected_endpoint in service_config
        assert '"host.docker.internal:host-gateway"' in service_config


def test_production_compose_uses_the_production_env_and_host_database() -> None:
    production = PROD_COMPOSE_PATH.read_text(encoding="utf-8")
    api = _service_block(production, "api")

    assert "env_file" not in api
    assert "@${POSTGRES_HOST:-host.docker.internal}:${POSTGRES_PORT:-5432}/" in api
    assert not re.search(r"(?m)^  database-init:$", production)


def test_compose_uses_typed_application_retention_defaults() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    production = PROD_COMPOSE_PATH.read_text(encoding="utf-8")

    for variable in (
        "ARTIFACT_TTL_SECONDS",
        "ARTIFACT_GC_INTERVAL_SECONDS",
        "ARTIFACT_GC_BATCH_SIZE",
        "ANALYSIS_REPORT_TTL_SECONDS",
    ):
        assert variable not in compose
        assert variable not in production


def test_api_receives_feature_flags_and_uses_typed_import_defaults() -> None:
    api = _service_block(COMPOSE_PATH.read_text(encoding="utf-8"), "api")

    assert "env_file" not in api
    for variable in (
        "MEDIA_IMPORT_ENABLED",
        "DOCUMENT_IMPORT_ENABLED",
        "SCREENPLAY_ANALYSIS_ENABLED",
        "MEDIA_IMPORT_MAX_BYTES",
        "DOCUMENT_IMPORT_MAX_BYTES",
        "IMPORT_UPLOAD_SESSION_TTL_SECONDS",
        "IMPORT_UPLOAD_PART_SIZE_BYTES",
        "IMPORT_UPLOAD_MAX_PARTS",
        "IMPORT_UPLOAD_MAX_CONCURRENCY",
        "IMPORT_RIGHTS_STATEMENT_VERSION",
    ):
        assert variable in api


def test_background_loops_share_one_private_worker_container() -> None:
    for path in (COMPOSE_PATH, PROD_COMPOSE_PATH):
        compose = path.read_text(encoding="utf-8")
        services = yaml.safe_load(compose)["services"]
        # Outbox, download, import and report run in one process.
        for retired in (
            "outbox",
            "worker-download",
            "worker-import",
            "worker-report",
            "provider-canary",
            "workspace-init",
            "provider-lease-redis",
        ):
            assert retired not in services
        worker = _service_block(compose, "worker")
        assert "SERVICE_ROLE: worker" in worker
        assert "RABBITMQ_WORKER_USER" in worker and "RABBITMQ_WORKER_PASS" in worker
        assert "env_file" not in worker
        assert "runner_egress_net" in worker
        assert "ports:" not in worker
        assert services["worker"]["networks"] == ["app_net", "runner_egress_net"]
        assert 'command: ["python", "-m", "app.workers.main"]' in worker


def test_compose_assigns_each_application_container_its_process_entrypoint() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    commands = {"api": "app.main", "worker": "app.workers.main"}

    for service, module in commands.items():
        service_config = _service_block(compose, service)
        assert f'command: ["python", "-m", "{module}"]' in service_config


def test_compose_isolates_media_dependencies_and_preserves_api_readiness() -> None:
    for path in (COMPOSE_PATH, PROD_COMPOSE_PATH):
        compose = yaml.safe_load(path.read_text(encoding="utf-8"))
        services = compose["services"]

        for service in ("api", "worker"):
            dependencies = services[service].get("depends_on", {})
            assert not (
                {"media-runner", "egress-proxy", *("session-runner",)}
                & set(dependencies)
            )
        assert "127.0.0.1:8111/health/ready" in " ".join(
            services["api"]["healthcheck"]["test"]
        )
        assert services["frontend"]["depends_on"]["api"]["condition"] == (
            "service_healthy"
        )
        assert "127.0.0.1:8101/" in " ".join(
            services["frontend"]["healthcheck"]["test"]
        )
        assert "127.0.0.1:19100/health/runtime" in " ".join(
            services["session-runner"]["healthcheck"]["test"]
        )

        for service in ("worker", "session-runner"):
            assert services[service]["stop_grace_period"] == "90s"


def test_project_documents_container_and_complete_local_entrypoints() -> None:
    root_readme = ROOT_README_PATH.read_text(encoding="utf-8")
    frontend_readme = FRONTEND_README_PATH.read_text(encoding="utf-8")
    startup_entrypoint = "docker compose up -d --build --wait"

    assert not STARTUP_SCRIPT_PATH.exists()
    assert not (ROOT.parent / "scripts/run-local-backend.py").exists()
    assert not (ROOT.parent / "scripts/start-local.sh").exists()
    assert not (ROOT.parent / "scripts/analysis-worker.sh").exists()
    assert not (ROOT / "app/workers/analysis/launchd.py").exists()
    assert startup_entrypoint in root_readme
    # Compose starts the business containers; host agents have explicit
    # installation commands and share the selected deployment environment.
    assert not (ROOT.parent / "start").exists()
    assert "app.workers.session.source_cli" not in root_readme
    assert not (ROOT / "app/workers/runner/provider_startup.py").exists()
    assert "provider_startup" not in root_readme
    assert "run-local-backend.py" not in root_readme
    assert "run-local-backend.py" not in frontend_readme
    assert "restart-project.ps1" not in root_readme
    for action in ("doctor", "install", "status"):
        assert (
            f"uv run python -m app.workers.analysis.agent_cli {action}" in root_readme
        )


def test_runtime_dependency_install_is_cached_and_retried() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "target=/var/cache/apt,sharing=locked" in dockerfile
    assert "target=/var/lib/apt/lists,sharing=locked" in dockerfile
    assert "apt-get -o Acquire::Retries=5 update" in dockerfile
    assert "apt-get -o Acquire::Retries=5 install" in dockerfile


def test_compose_pins_shared_runner_workspace_to_the_mounted_container_path() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))

    for service in ("worker", "session-runner"):
        service_config = compose["services"][service]
        assert service_config["environment"]["RUNNER_WORKSPACE_ROOT"] == "/work"
        assert "runner_work:/work" in service_config["volumes"]
    # The image owns /work, so a fresh volume starts private without an init job.
    assert "install -d -o 10001 -g 10001 -m 0700 /work" in DOCKERFILE_PATH.read_text(
        encoding="utf-8"
    )


def test_anonymous_runner_retains_private_network_and_workspace() -> None:
    for path in (COMPOSE_PATH, PROD_COMPOSE_PATH):
        compose = yaml.safe_load(path.read_text(encoding="utf-8"))
        services = compose["services"]
        runner = services["session-runner"]
        assert "session-broker" not in services
        assert "runner_rpc_net" not in compose["networks"]
        assert set(runner["networks"]) == {"runner_egress_net", "youtube_pot_net"}
        assert runner["volumes"] == [
            "runner_work:/work",
            "browser_profiles:/var/lib/framefetch-browser",
        ]
        assert (
            runner["environment"]["RUNNER_BROWSER_PROFILE_ROOT"]
            == "/var/lib/framefetch-browser"
        )
        assert runner["shm_size"] == "256m"
        assert "ports" not in runner
        assert "DATABASE_URL" not in runner["environment"]
        assert not any(
            key.startswith("RUNNER_SESSION_") for key in runner["environment"]
        )
        assert runner["read_only"] is True
        assert "proxy_uplink_net" not in runner["networks"]
        for service in ("api", "worker"):
            assert "runner_egress_net" in services[service]["networks"]


def test_production_compose_is_the_only_production_topology_file() -> None:
    assert not (ROOT.parent / "docker-compose-browser.yml").exists()
    assert not (ROOT.parent / "docker-compose-session-files.yml").exists()
    assert PROD_COMPOSE_PATH.is_file()
    assert "-f docker-compose-prod.yml" in ROOT_README_PATH.read_text(encoding="utf-8")


def test_projects_build_and_run_separate_images() -> None:
    for path in (COMPOSE_PATH, PROD_COMPOSE_PATH):
        services = yaml.safe_load(path.read_text())["services"]
        backend = services["api"]
        frontend = services["frontend"]
        assert backend["build"]["context"] == "./backend"
        assert frontend["build"]["context"] == "./frontend"
        assert backend["image"] != frontend["image"]
        assert frontend["healthcheck"]["test"][1] == "node"
    assert not (ROOT.parent / "Dockerfile").exists()
    assert "frontend-builder" not in (ROOT / "Dockerfile").read_text()
    assert "python:" not in (ROOT.parent / "frontend/Dockerfile").read_text()


def test_compose_application_roles_share_the_selected_release_image() -> None:
    for path, tag in ((COMPOSE_PATH, "local"), (PROD_COMPOSE_PATH, "prod")):
        services = yaml.safe_load(path.read_text())["services"]
        for name, config in services.items():
            build = config.get("build", {})
            if build.get("context") != "./backend":
                continue
            # Only the session browser has its own target: it adds Chromium.
            if build.get("target") == "session-browser":
                assert config["image"] == f"video-session-browser:{tag}", name
            else:
                assert "target" not in build, name
                assert config["image"] == f"framefetch-server:{tag}", name


def test_runtime_base_images_are_pinned_without_host_architecture_override() -> None:
    for path in (DOCKERFILE_PATH, ROOT.parent / "frontend/Dockerfile"):
        stages = re.findall(r"^FROM (\S+) AS (\S+)", path.read_text(), re.MULTILINE)
        assert stages
        earlier: set[str] = set()
        for reference, name in stages:
            # A stage may build on an earlier stage; external bases are pinned.
            assert reference in earlier or re.fullmatch(
                r"[^@]+@sha256:[0-9a-f]{64}", reference
            ), reference
            earlier.add(name)
        assert "FROM --platform=" not in path.read_text()


def test_anonymous_and_guest_execution_services_are_removed():
    for path in (COMPOSE_PATH, PROD_COMPOSE_PATH):
        services = yaml.safe_load(path.read_text())["services"]
        assert (
            not {
                "media-runner",
                "provider-guest",
                "provider-guest-init",
                "douyin-guest-runner",
            }
            & services.keys()
        )


def test_collaboration_contract_uses_the_final_execution_design() -> None:
    agents = (ROOT.parent / "AGENTS.md").read_text()
    assert (
        "公开线路（content_scope=public）只处理能够正向证明为公开、免费、非 DRM 的 "
        "HTTP(S) 内容；"
        "带着 Cookie 也不扩张到 private、follow-only、会员/购买或地域受限内容。"
    ) in agents
    assert (
        "personal_full 只适用于腾讯视频、优酷：处理账号可访问的完整非 DRM 单视频，"
        "必须保留原始完整时长，并通过最终文件校验。"
    ) in agents
    assert (
        "identity 与 content_scope 是两个独立维度，读取账号材料不等于放宽内容范围。"
    ) in agents
    assert "解析引擎第 9 节的十二字段非敏感摘要" in agents
    assert "第 8 节的十三类" in agents
    assert "layer、stage、gate、结构化 evidence" in agents
    assert "六字段" not in agents
    assert "十类失败" not in agents
