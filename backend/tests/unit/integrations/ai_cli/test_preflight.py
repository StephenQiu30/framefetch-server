from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from app.integrations.ai_cli.errors import AnalysisCliError
from app.integrations.ai_cli.preflight import preflight


def executable(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o700)
    return path


def runner(
    argv: Sequence[str], environment: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    del environment
    command = tuple(argv[1:])
    if command == ("--version",):
        stdout = "codex-cli 0.149.0"
    elif command == ("app-server", "--help"):
        stdout = "--listen generate-json-schema"
    elif command == ("login", "status"):
        stdout = "Logged in using ChatGPT"
    elif command == ("--help",):
        stdout = "--safe-mode --json-schema --strict-mcp-config"
    elif command == ("auth", "status", "--json"):
        stdout = json.dumps(
            {
                "loggedIn": True,
                "authMethod": "oauth_token",
                "apiProvider": "firstParty",
            }
        )
    elif command == ("-version",):
        stdout = "media 1.2.3"
    else:
        return subprocess.CompletedProcess(argv, 1, "", "unsupported")
    return subprocess.CompletedProcess(argv, 0, stdout, "")


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_preflight_accepts_only_supported_oauth_cli(
    tmp_path: Path, provider: str
) -> None:
    cli = executable(tmp_path, provider)
    ffmpeg = executable(tmp_path, "ffmpeg")
    ffprobe = executable(tmp_path, "ffprobe")

    capabilities = preflight(
        provider,
        cli_binary=cli,
        ffmpeg_binary=ffmpeg,
        ffprobe_binary=ffprobe,
        environment={"PATH": str(tmp_path)},
        runner=runner,
    )

    assert capabilities.provider == provider
    assert capabilities.version == "codex-cli 0.149.0"


def test_preflight_rejects_non_oauth_claude(tmp_path: Path) -> None:
    cli = executable(tmp_path, "claude")
    media = executable(tmp_path, "media")

    def api_key_runner(
        argv: Sequence[str], environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        result = runner(argv, environment)
        if tuple(argv[1:]) == ("auth", "status", "--json"):
            result = subprocess.CompletedProcess(
                argv,
                0,
                json.dumps({"loggedIn": True, "authMethod": "api_key"}),
                "",
            )
        return result

    with pytest.raises(AnalysisCliError, match="analysis_cli_not_authenticated"):
        preflight(
            "claude",
            cli_binary=cli,
            ffmpeg_binary=media,
            ffprobe_binary=media,
            environment={"PATH": str(tmp_path)},
            runner=api_key_runner,
        )


def test_preflight_classifies_media_dependency_failure(tmp_path: Path) -> None:
    cli = executable(tmp_path, "codex")
    media = executable(tmp_path, "media")

    def failing_media_runner(
        argv: Sequence[str], environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        if tuple(argv[1:]) == ("-version",):
            return subprocess.CompletedProcess(argv, 1, "", "missing dependency")
        return runner(argv, environment)

    with pytest.raises(AnalysisCliError, match="analysis_cli_unavailable"):
        preflight(
            "codex",
            cli_binary=cli,
            ffmpeg_binary=media,
            ffprobe_binary=media,
            environment={"PATH": str(tmp_path)},
            runner=failing_media_runner,
        )
