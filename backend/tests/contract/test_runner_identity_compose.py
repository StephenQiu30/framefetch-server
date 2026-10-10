"""Ordinary Compose rebuilds recover the installed identity without shell exports."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TOKEN = "synthetic-runner-token-with-at-least-32-bytes"


@pytest.mark.parametrize("installed", [False, True])
def test_normal_compose_start_scopes_installed_identity_to_runner(tmp_path, installed):
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose CLI is needed to resolve optional env_file")
    compose = tmp_path / "docker-compose.yml"
    shutil.copyfile(ROOT / "docker-compose.yml", compose)
    if installed:
        environment = tmp_path / ".local-runtime/identity/runner.env"
        environment.parent.mkdir(parents=True, mode=0o700)
        environment.write_text(f"COOKIE_SOURCE_TOKEN={TOKEN}\n")
        environment.chmod(0o600)
    for shell_token in (None, "stale-shell-token-must-not-override-installation"):
        shell = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", str(tmp_path)),
        }
        if shell_token:
            shell["COOKIE_SOURCE_TOKEN"] = shell_token
        shell["COOKIE_SOURCE_PAIRING_KEY"] = "host-only-pairing-key"
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose), "config", "--format", "json"],
            cwd=tmp_path,
            env=shell,
            capture_output=True,
            text=True,
            check=True,
        )
        services = json.loads(result.stdout)["services"]
        for name, service in services.items():
            values = service.get("environment", {})
            assert "COOKIE_SOURCE_PAIRING_KEY" not in values
            if name == "session-runner" and installed:
                assert values.get("COOKIE_SOURCE_TOKEN") == TOKEN
            else:
                assert "COOKIE_SOURCE_TOKEN" not in values
