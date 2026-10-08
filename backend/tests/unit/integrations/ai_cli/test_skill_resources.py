from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.integrations.ai_cli.codex_mcp import skill_resource_arguments
from app.integrations.ai_cli.errors import AnalysisCliError
from app.integrations.ai_cli.skill_resources import (
    MAX_READS,
    SkillResources,
)
from app.services.analysis.rules.enums import AnalysisInputKind
from app.services.analysis.skills.registry import BUILTIN_ANALYSIS_SKILLS
from app.services.analysis.skills.upstream_catalog import (
    RESOURCE_POLICY,
    prepare_resource_policy,
)
from app.services.analysis_execution.errors import AnalysisArtifactError
from tests.unit.services.analysis.skills.test_upstream_catalog import fixture_catalog


def resources(tmp_path: Path) -> SkillResources:
    catalog = fixture_catalog(tmp_path)
    workspace = tmp_path / "job"
    (workspace / "policy").mkdir(parents=True)
    (workspace / RESOURCE_POLICY).write_text(
        json.dumps({"example": catalog.verify("example").fingerprint})
    )
    return SkillResources(workspace, catalog=catalog)


def test_resource_returns_entire_reference_and_only_records_metadata(tmp_path):
    tool = resources(tmp_path)
    result = tool.call(
        "read_skill_resource", {"package_id": "example", "path": "references/full.md"}
    )
    assert result == {
        "content": [{"type": "text", "text": "# Full\n\nStart\n\n## End\nTail\n"}]
    }
    receipt = (tool.workspace / "work/skill-resource-receipts.jsonl").read_text()
    assert "Tail" not in receipt
    assert json.loads(receipt)["size_bytes"] == 27


@pytest.mark.parametrize(
    "arguments",
    [
        {"package_id": "ecc", "path": "skills/article-writing/SKILL.md"},
        {"package_id": "example", "path": "../manifest.json"},
        {"package_id": "example", "path": "LICENSE"},
        {"package_id": "example", "path": "references/full.md", "command": "whoami"},
    ],
)
def test_only_authorized_markdown_can_be_read(tmp_path, arguments):
    tool = resources(tmp_path)
    assert tool.call("read_skill_resource", arguments)["isError"] is True
    assert not (tool.workspace / "work").exists()


def test_read_budget_is_enforced_without_truncating_files(tmp_path):
    tool = resources(tmp_path)
    args = {"package_id": "example", "path": "references/full.md"}
    for _ in range(MAX_READS):
        assert "isError" not in tool.call("read_skill_resource", args)
    assert tool.call("read_skill_resource", args)["isError"] is True
    tool = resources(tmp_path / "second")
    tool.bytes_read = 1024 * 1024
    assert tool.call("read_skill_resource", args)["isError"] is True
    assert tool.reads == 0


def test_mutated_resource_after_initialization_is_rejected(tmp_path):
    tool = resources(tmp_path)
    (tool.catalog.root / "example/references/full.md").write_text("Changed")
    assert tool.call(
        "read_skill_resource", {"package_id": "example", "path": "references/full.md"}
    )["isError"]


def test_policy_freezes_package_and_cli_exposes_only_read_tool(tmp_path):
    (tmp_path / "policy").mkdir()
    skill = BUILTIN_ANALYSIS_SKILLS.get(
        "screenplay-analysis", AnalysisInputKind.SCREENPLAY
    )
    assert skill is not None
    prepare_resource_policy(tmp_path, skill.instructions)
    tool = SkillResources(tmp_path)
    assert set(tool.packages) == {"screenwriting", "drama"}
    args = skill_resource_arguments(tmp_path)
    assert 'mcp_servers.skill_resources.enabled_tools=["read_skill_resource"]' in args
    prepare_resource_policy(tmp_path, "Historical method without upstream package")
    assert not (tmp_path / RESOURCE_POLICY).exists()
    assert skill_resource_arguments(tmp_path) == ()


def test_unknown_package_version_is_rejected_before_model_call(tmp_path):
    (tmp_path / "policy").mkdir()
    snapshot = (
        '\n<framefetch_upstream_packages>\n{"screenwriting":"'
        + "0" * 64
        + '"}\n</framefetch_upstream_packages>'
    )
    with pytest.raises(AnalysisArtifactError) as error:
        prepare_resource_policy(tmp_path, snapshot)
    assert error.value.no_model_execution
    assert not (tmp_path / RESOURCE_POLICY).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["api", "claude"])
async def test_unsupported_adapters_reject_upstream_before_inference(tmp_path, kind):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.integrations.ai_api.analyzer import ApiAnalyzer
    from app.integrations.ai_cli.claude_screenplay import ClaudeCliScreenplayAnalyzer

    cls = ApiAnalyzer if kind == "api" else ClaudeCliScreenplayAnalyzer
    analyzer = object.__new__(cls)
    analyzer._invoke = AsyncMock()
    skill = BUILTIN_ANALYSIS_SKILLS.get(
        "screenplay-analysis", AnalysisInputKind.SCREENPLAY
    )
    request = SimpleNamespace(skill_instructions=skill.instructions)
    operation = analyzer.analyze_screenplay if kind == "api" else analyzer.analyze
    with pytest.raises(AnalysisCliError) as error:
        await operation(request)
    assert error.value.no_model_execution
    assert error.value.code == "analysis_cli_unsupported"
    analyzer._invoke.assert_not_called()
