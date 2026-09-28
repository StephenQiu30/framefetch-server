"""Process credentials stay scoped when deployment environment files grow."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SECRETS = {
    "SMTP_PASSWORD",
    "AUTH_JWT_SECRET",
    "AUTH_BOOTSTRAP_ADMIN_SECRET",
    "REQUEST_FINGERPRINT_SECRET",
    "METRICS_ACCESS_KEY",
    "URL_ENCRYPTION_KEY",
    "RUNNER_HMAC_SECRET",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "PROVIDER_CANARY_TARGETS",
}
STORAGE = {"MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"}
ALLOWED = {
    "api": STORAGE
    | {
        "SMTP_PASSWORD",
        "AUTH_JWT_SECRET",
        "AUTH_BOOTSTRAP_ADMIN_SECRET",
        "REQUEST_FINGERPRINT_SECRET",
        "METRICS_ACCESS_KEY",
        "URL_ENCRYPTION_KEY",
        "RUNNER_HMAC_SECRET",
    },
    "outbox": set(),
    "worker-download": STORAGE
    | {"URL_ENCRYPTION_KEY", "RUNNER_HMAC_SECRET", "REQUEST_FINGERPRINT_SECRET"},
    "worker-import": STORAGE,
    "worker-report": STORAGE,
    "provider-canary": STORAGE
    | {"URL_ENCRYPTION_KEY", "RUNNER_HMAC_SECRET", "PROVIDER_CANARY_TARGETS"},
}


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose-prod.yml"])
def test_business_roles_use_explicit_scoped_secret_allowlists(filename):
    services = yaml.safe_load((ROOT / filename).read_text())["services"]
    for name, allowed in ALLOWED.items():
        service = services[name]
        assert "env_file" not in service
        environment = service["environment"]
        assert SECRETS & environment.keys() == allowed
        assert {key for key in environment if key.endswith(("_PASS", "_PASSWORD"))} == (
            {"SMTP_PASSWORD"} if name == "api" else set()
        )
        assert "DATABASE_URL" in environment
        assert "APP_ENV" in environment
    assert "REDIS_URL" not in services["worker-download"]["environment"]
    assert "RABBITMQ_URL" not in services["provider-canary"]["environment"]
