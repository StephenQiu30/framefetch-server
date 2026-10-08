from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[3] / ".github/workflows/ci.yml"


def test_ci_is_limited_to_deterministic_system_tests() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]

    assert set(jobs) == {"backend-tests", "frontend-tests", "docs"}
    assert {job["name"] for job in jobs.values()} == {
        "Backend tests",
        "Frontend tests",
        "Docs",
    }

    commands = "\n".join(
        step.get("run", "") for job in jobs.values() for step in job["steps"]
    )
    assert "pytest -q" in commands
    assert "pnpm test" in commands
    assert "pnpm build" in commands
    assert "docker compose" not in commands
    assert "npm audit" not in commands


def test_ci_actions_are_pinned_to_commits() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    for job in workflow["jobs"].values():
        for step in job["steps"]:
            reference = step.get("uses")
            if reference is None:
                continue
            _, revision = reference.rsplit("@", maxsplit=1)
            assert len(revision) == 40
            assert all(character in "0123456789abcdef" for character in revision)


def test_ci_keeps_all_quality_gates_blocking() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    _assert_quality_gates(workflow)


def _assert_quality_gates(workflow: dict) -> None:
    expected = {
        "backend-tests": (
            "sudo apt-get install --yes --no-install-recommends "
            "redis-server redis-tools",
            "command -v redis-server",
            "command -v redis-cli",
            "uv sync --frozen --dev",
            "uv run --frozen ruff check app tests",
            "uv run --frozen ruff format --check app tests",
            "uv run --frozen mypy app",
            "uv run --frozen pytest -q",
        ),
        "frontend-tests": (
            "pnpm install --frozen-lockfile",
            'OPENAPI_SCHEMA_URL="$RUNNER_TEMP/framefetch-openapi.json" '
            "pnpm openapi:check",
            "pnpm format:check",
            "pnpm lint",
            "pnpm test",
            "pnpm build",
        ),
        "docs": (
            "node --test extension/*.test.cjs",
            "node backend/scripts/check_docs.mjs",
        ),
    }
    # PyYAML uses YAML 1.1, where the unquoted `on` key is a boolean.
    triggers = workflow[True]
    assert triggers["push"]["branches"] == ["main"]
    assert triggers["pull_request"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}
    for name, required in expected.items():
        job = workflow["jobs"][name]
        assert "if" not in job and not job.get("continue-on-error")
        commands = []
        for step in job["steps"]:
            assert "if" not in step and not step.get("continue-on-error")
            commands.extend(step.get("run", "").splitlines())
        assert all(command in commands for command in required)
        assert not any(
            "|| true" in command or "set +e" in command for command in commands
        )


def test_quality_gate_contract_rejects_missing_or_nonblocking_checks() -> None:
    from copy import deepcopy

    import pytest

    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    for mutation in ("missing-command", "skip-job", "ignore-failure"):
        changed = deepcopy(workflow)
        job = changed["jobs"]["frontend-tests"]
        if mutation == "missing-command":
            job["steps"][-1]["run"] = job["steps"][-1]["run"].replace("pnpm lint", "")
        elif mutation == "skip-job":
            job["if"] = "false"
        else:
            job["steps"][-1]["continue-on-error"] = True
        with pytest.raises(AssertionError):
            _assert_quality_gates(changed)


def test_ci_toolchain_matches_frontend_manifest() -> None:
    import json

    root = WORKFLOW_PATH.parents[2]
    package = json.loads((root / "frontend/package.json").read_text())
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    steps = workflow["jobs"]["frontend-tests"]["steps"]
    assert any(
        step.get("run") == f"npm install --global {package['packageManager']}"
        for step in steps
    )
    assert (
        "git ls-files --others --exclude-standard -- src/api"
        in package["scripts"]["openapi:check"]
    )


def test_binary_frontend_assets_are_not_forced_to_text() -> None:
    import subprocess

    root = WORKFLOW_PATH.parents[2]
    assets = sorted((root / "frontend/public").glob("*.png"))
    assets += sorted((root / "frontend/public").glob("*.ico"))
    assert assets
    result = subprocess.run(
        ["git", "check-attr", "text", "--", *map(str, assets)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert all(not line.endswith(": set") for line in result.stdout.splitlines())
