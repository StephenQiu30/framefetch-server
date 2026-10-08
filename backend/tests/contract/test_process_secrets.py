"""Process credentials stay scoped when deployment environment files grow."""

from pathlib import Path

import pytest
from tests.compose import load_compose

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
    # The single background worker holds exactly its components' union.
    "worker": STORAGE
    | {
        "URL_ENCRYPTION_KEY",
        "RUNNER_HMAC_SECRET",
        "REQUEST_FINGERPRINT_SECRET",
    },
}


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose-prod.yml"])
def test_business_roles_use_explicit_scoped_secret_allowlists(filename):
    services = load_compose(ROOT / filename)["services"]
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
    # Neither the business Redis nor the auth secrets reach background loops.
    worker = services["worker"]["environment"]
    assert "REDIS_URL" not in worker
    assert "AUTH_JWT_SECRET" not in worker
    assert "RABBITMQ_WORKER_USER" in worker["RABBITMQ_URL"]
