from __future__ import annotations

import json

from app.integrations.ai_cli.errors import classify_cli_failure
from app.services.analysis.rules.model_schema import analysis_output_schema


def test_schema_uses_codex_and_claude_supported_subset() -> None:
    schema = analysis_output_schema("zh-CN")
    serialized = json.dumps(schema)

    for unsupported in (
        '"$schema"',
        '"uniqueItems"',
        '"minItems"',
        '"maxItems"',
        '"minLength"',
        '"maxLength"',
        '"pattern"',
    ):
        assert unsupported not in serialized
    assert schema["additionalProperties"] is False


def test_schema_exposes_continuous_visual_beat_boundary() -> None:
    schema = analysis_output_schema("zh-CN")
    transition = schema["properties"]["shots"]["items"]["properties"]["transition_in"]

    assert transition["enum"] == [
        "cut",
        "fade",
        "dissolve",
        "wipe",
        "continuous",
        "none",
        "unknown",
    ]


def test_claude_max_turns_maps_to_resource_limit() -> None:
    error = classify_cli_failure(
        b'{"subtype":"error_max_turns","terminal_reason":"max_turns"}'
    )

    assert error.code == "analysis_resource_limit"


def test_invalid_provider_json_schema_is_not_reported_as_resource_limit() -> None:
    error = classify_cli_failure(
        b'{"code":"invalid_json_schema","message":"unsupported keyword"}'
    )

    assert error.code == "analysis_cli_unsupported"


def test_codex_banner_does_not_hide_transport_failure() -> None:
    error = classify_cli_failure(
        b"sandbox: custom permissions\nerror sending request for url"
    )

    assert error.code == "analysis_cli_failed"


def test_explicit_sandbox_initialization_failure_is_classified() -> None:
    error = classify_cli_failure(b"failed to initialize sandbox policy")

    assert error.code == "analysis_sandbox_unavailable"


def test_codex_instruction_permission_failure_is_classified() -> None:
    error = classify_cli_failure(
        b"failed to load AGENTS.md instructions for environment `local`: "
        b"Operation not permitted (os error 1)"
    )

    assert error.code == "analysis_sandbox_unavailable"


def test_claude_windows_feature_gate_failure_is_classified() -> None:
    error = classify_cli_failure(
        b"sandbox required but unavailable: Windows sandbox feature gate off"
    )

    assert error.code == "analysis_sandbox_unavailable"
