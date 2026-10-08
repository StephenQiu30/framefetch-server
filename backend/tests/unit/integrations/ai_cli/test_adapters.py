from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from app.integrations.ai_cli.claude import ClaudeCliVideoAnalyzer
from app.integrations.ai_cli.codex import CodexAppServerVideoAnalyzer
from app.integrations.ai_cli.config import CliAdapterConfig
from app.integrations.ai_cli.errors import AnalysisCliError
from tests.unit.integrations.ai_cli.helpers import (
    FakeCodexAppServer,
    FakeSupervisor,
    request,
    screenplay_request,
    screenplay_supervisor,
    screenplay_synthesis_request,
)
from tests.unit.workers.analysis.fixtures import (
    valid_mapping,
    valid_screenplay_mapping,
)


def config() -> CliAdapterConfig:
    return CliAdapterConfig(
        binary=Path(sys.executable),
        model="controlled-model",
        ffmpeg=Path(sys.executable),
        ffprobe=Path(sys.executable),
    )


@pytest.mark.asyncio
async def test_codex_uses_app_server_with_structured_ephemeral_call(
    tmp_path: Path,
) -> None:
    client = FakeCodexAppServer()
    analyzer = CodexAppServerVideoAnalyzer(config(), client=client)

    payload = await analyzer.analyze(request(tmp_path))

    assert payload == valid_mapping()
    assert client.root == tmp_path / "job"
    assert client.duration_ms == 2_000
    assert "input/video.bin" in client.prompt
    assert "完整视频已通过 video_observer 工具交给你" in client.prompt
    assert isinstance(client.schema, dict)


@pytest.mark.asyncio
async def test_claude_returns_structured_output_without_prompt_argv(
    tmp_path: Path,
) -> None:
    supervisor = FakeSupervisor(provider="claude")
    analyzer = ClaudeCliVideoAnalyzer(config(), supervisor=supervisor)  # type: ignore[arg-type]

    payload = await analyzer.analyze(request(tmp_path))

    assert payload == valid_mapping()
    assert "--safe-mode" in supervisor.argv
    assert "--strict-mcp-config" in supervisor.argv
    assert "--json-schema" in supervisor.argv
    assert supervisor.input_bytes is not None
    assert b"input/video.bin" in supervisor.input_bytes
    assert all("input/video.bin" not in item for item in supervisor.argv)
    assert _has_no_api_keys(supervisor.environment)


@pytest.mark.asyncio
async def test_claude_screenplay_is_single_turn_and_disables_all_tools(
    tmp_path: Path,
) -> None:
    supervisor = screenplay_supervisor()
    analyzer = ClaudeCliVideoAnalyzer(config(), supervisor=supervisor)  # type: ignore[arg-type]
    screenplay = screenplay_request(tmp_path)

    payload = await analyzer.analyze_screenplay(screenplay)

    assert payload == valid_screenplay_mapping()
    assert supervisor.argv[supervisor.argv.index("--tools") + 1] == ""
    assert supervisor.argv[supervisor.argv.index("--max-turns") + 1] == "1"
    assert "--allowedTools" not in supervisor.argv
    assert "Bash,Read,Write,Edit,WebFetch,WebSearch,Agent" in supervisor.argv
    assert supervisor.input_bytes is not None
    encoded = json.dumps(screenplay.screenplay_text, ensure_ascii=False).encode()
    assert encoded in supervisor.input_bytes
    assert all(screenplay.screenplay_text not in value for value in supervisor.argv)
    assert _has_no_api_keys(supervisor.environment)


@pytest.mark.asyncio
async def test_codex_screenplay_is_structured_and_has_no_tools(tmp_path: Path) -> None:
    client = FakeCodexAppServer(valid_screenplay_mapping())
    analyzer = CodexAppServerVideoAnalyzer(config(), client=client)
    screenplay = screenplay_request(tmp_path)

    payload = await analyzer.analyze_screenplay(screenplay)

    assert payload == valid_screenplay_mapping()
    assert client.duration_ms is None
    assert json.dumps(screenplay.screenplay_text, ensure_ascii=False) in client.prompt
    assert isinstance(client.schema, dict)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["codex", "claude"])
async def test_screenplay_synthesis_uses_validated_chunk_results_without_tools(
    tmp_path: Path, provider: str
) -> None:
    payload = valid_screenplay_mapping()
    payload.pop("scenes")
    supervisor = FakeSupervisor(provider="claude", payload=payload)
    client = FakeCodexAppServer(payload)
    analyzer = (
        CodexAppServerVideoAnalyzer(config(), client=client)
        if provider == "codex"
        else ClaudeCliVideoAnalyzer(config(), supervisor=supervisor)  # type: ignore[arg-type]
    )
    request_value = screenplay_synthesis_request(tmp_path)

    result = await analyzer.synthesize_screenplay_analysis(request_value)

    assert result == payload
    if provider == "codex":
        assert request_value.chunk_results_json in client.prompt
        assert client.duration_ms is None
    else:
        assert supervisor.input_bytes is not None
        assert request_value.chunk_results_json.encode() in supervisor.input_bytes
        assert all(
            request_value.chunk_results_json not in value for value in supervisor.argv
        )
        assert not any("video_observer" in item for item in supervisor.argv)
        assert _has_no_api_keys(supervisor.environment)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["codex", "claude"])
async def test_screenplay_accepts_valid_result_when_diagnostic_stderr_is_truncated(
    tmp_path: Path, provider: str
) -> None:
    payload = valid_screenplay_mapping()
    supervisor = FakeSupervisor(
        provider="claude",
        payload=payload,
        stderr=b"bounded diagnostic prefix",
        stderr_truncated=True,
    )
    analyzer = (
        CodexAppServerVideoAnalyzer(config(), client=FakeCodexAppServer(payload))
        if provider == "codex"
        else ClaudeCliVideoAnalyzer(config(), supervisor=supervisor)  # type: ignore[arg-type]
    )

    result = await analyzer.analyze_screenplay(screenplay_request(tmp_path))

    assert result == payload


@pytest.mark.asyncio
async def test_codex_classifies_failed_schema_before_stderr_truncation(
    tmp_path: Path,
) -> None:
    client = FakeCodexAppServer(error=AnalysisCliError("analysis_cli_unsupported"))
    analyzer = CodexAppServerVideoAnalyzer(config(), client=client)

    with pytest.raises(AnalysisCliError) as error:
        await analyzer.analyze_screenplay(screenplay_request(tmp_path))

    assert error.value.code == "analysis_cli_unsupported"


@pytest.mark.asyncio
async def test_claude_screenplay_rejects_oversized_schema_before_process(
    tmp_path: Path,
) -> None:
    supervisor = screenplay_supervisor()
    analyzer = ClaudeCliVideoAnalyzer(config(), supervisor=supervisor)  # type: ignore[arg-type]
    screenplay = screenplay_request(tmp_path)
    screenplay = replace(
        screenplay,
        source_scene_ids=tuple(
            f"scene-{index:04d}-{'a' * 300}" for index in range(1, 121)
        ),
    )

    with pytest.raises(AnalysisCliError) as error:
        await analyzer.analyze_screenplay(screenplay)

    assert error.value.code == "analysis_resource_limit"
    assert supervisor.argv == ()


def _has_no_api_keys(environment: dict[str, str]) -> bool:
    forbidden = {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
    }
    return forbidden.isdisjoint(environment)
