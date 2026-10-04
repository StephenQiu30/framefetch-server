from __future__ import annotations

from pathlib import Path

import pytest
from app.integrations.analysis_skill_catalog import BuiltinAnalysisSkillCatalog
from app.services.analysis.rules.enums import AnalysisInputKind, AnalysisResultContract
from app.services.analysis.skills.modules import SOURCE_MODULES
from app.services.analysis.skills.registry import (
    BUILTIN_ANALYSIS_SKILLS,
    AnalysisSkillRegistry,
)

SKILLS_ROOT = (
    Path(__file__).resolve().parents[3] / "app" / "services" / "analysis" / "skills"
)


def _document(
    name: str,
    *,
    input_kind: str = "video",
    contract: str = "video-visual-analysis",
    extra_top: str = "",
    extra_metadata: str = "",
    references: str = "",
) -> str:
    return f"""---
name: {name}
description: Test skill for validating analysis registry behavior.
license: MIT
{extra_top}metadata:
  video-server-display-name: Test Skill
  video-server-default-prompt: Analyze the supplied input.
  video-server-order: "10"
  video-server-input-kinds: {input_kind}
  video-server-output-contract: {contract}
{extra_metadata}{references}---

# Test

Use only supplied evidence.
"""


def _write_skill(root: Path, name: str, document: str | None = None) -> Path:
    skill_dir = root / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(document or _document(name), encoding="utf-8")
    return skill_dir


def test_builtin_skills_are_filtered_ordered_and_contract_bound() -> None:
    catalog = BuiltinAnalysisSkillCatalog()

    video = catalog.list(AnalysisInputKind.VIDEO)
    screenplay = catalog.list(AnalysisInputKind.SCREENPLAY)

    assert [skill.id for skill in video] == [
        "video-review",
        "video-to-article",
        "video-breakdown",
        "short-video-packaging",
    ]
    assert [skill.id for skill in screenplay] == [
        "screenplay-analysis",
        "screenplay-rewrite",
    ]
    assert [skill.id for skill in catalog.list(AnalysisInputKind.CONTENT)] == [
        "content-writing"
    ]
    assert {skill.result_contract for skill in video} == {
        AnalysisResultContract.VIDEO_ARTICLE,
        AnalysisResultContract.STRUCTURED_REPORT,
    }
    assert catalog.resolve("director-breakdown", AnalysisInputKind.VIDEO) is None
    assert catalog.resolve("content-article", AnalysisInputKind.CONTENT) is None


def test_builtin_resolution_compiles_allowlisted_reference_and_sha256() -> None:
    catalog = BuiltinAnalysisSkillCatalog()

    resolved = catalog.resolve("screenplay-analysis", AnalysisInputKind.SCREENPLAY)

    assert resolved is not None
    assert "# Source module: drama-story-script" in resolved.instructions
    assert "# Source module: sw-story-structure" in resolved.instructions
    assert "# Reference: references/output-contract.md" in resolved.instructions
    assert "完整场景调用必须返回以下字段" in resolved.instructions
    assert "汇总调用" in resolved.instructions
    assert "source_scene_id" in resolved.instructions
    assert len(resolved.instructions_sha256) == 64
    assert catalog.resolve("screenplay-analysis", AnalysisInputKind.VIDEO) is None
    assert BUILTIN_ANALYSIS_SKILLS.get("missing", AnalysisInputKind.VIDEO) is None


@pytest.mark.parametrize(
    "skill_id",
    ["video-review", "video-to-article", "video-breakdown", "short-video-packaging"],
)
def test_video_methods_have_real_stage_boundaries(skill_id):
    from app.services.analysis_execution.editorial_plan import stage_method

    skill = BUILTIN_ANALYSIS_SKILLS.get(skill_id, AnalysisInputKind.VIDEO)
    assert skill is not None
    for stage in ("plan", "draft", "review"):
        method = stage_method(skill.instructions, stage)
        assert f"# {stage.capitalize()}" in method
        assert all(
            f"# {other.capitalize()}\n" not in method
            for other in {"plan", "draft", "review"} - {stage}
        )
    article = BUILTIN_ANALYSIS_SKILLS.get("video-to-article", AnalysisInputKind.VIDEO)
    assert "可以全文没有小标题" in article.instructions
    assert "审校记录不进入正文" in article.instructions


def test_article_uses_baoyu_title_method_without_hook_or_execution_instructions() -> (
    None
):
    article = BUILTIN_ANALYSIS_SKILLS.get("video-to-article", AnalysisInputKind.VIDEO)
    assert article is not None
    assert "# Source module: baoyu-article-title" in article.instructions
    assert "## Straightforward Style" in article.instructions
    assert "**Descriptive**" in article.instructions
    assert "**Declarative**" in article.instructions
    for excluded in (
        "## Hook Formulas",
        "## Title Principles",
        "## Prohibited Patterns",
    ):
        assert excluded not in article.instructions
    assert "scripts/main.ts" not in article.instructions
    assert "baoyu-post-to-wechat" not in article.instructions
    assert not (SKILLS_ROOT / "modules" / "baoyu-skills" / "scripts").exists()


@pytest.mark.parametrize(
    ("document", "message"),
    (
        ("# missing metadata", "frontmatter"),
        (_document("Bad-Skill"), "skill id"),
        (
            _document("bad-skill", extra_top="allowed-tools: Bash\n"),
            "frontmatter field",
        ),
        (
            _document("bad-skill", extra_metadata="  video-server-unknown: value\n"),
            "product metadata",
        ),
        (_document("bad-skill", input_kind="audio"), "input kind"),
        (_document("bad-skill", contract="unknown"), "result contract"),
        (
            _document("bad-skill", input_kind="screenplay"),
            "incompatible",
        ),
        (
            _document(
                "bad-skill",
                references="  video-server-references: ../outside.md\n",
            ),
            "unsafe",
        ),
        (
            _document(
                "bad-skill",
                references="  video-server-references: /absolute.md\n",
            ),
            "unsafe",
        ),
    ),
)
def test_registry_rejects_invalid_skill_contracts(
    tmp_path: Path, document: str, message: str
) -> None:
    _write_skill(tmp_path, "bad-skill", document)

    with pytest.raises(ValueError, match=message):
        AnalysisSkillRegistry.from_directory(tmp_path)


def test_registry_rejects_unlisted_references_and_executable_resources(
    tmp_path: Path,
) -> None:
    skill_dir = _write_skill(tmp_path, "bad-skill")
    references = skill_dir / "references"
    references.mkdir()
    (references / "hidden.md").write_text("hidden", encoding="utf-8")

    with pytest.raises(ValueError, match="unlisted"):
        AnalysisSkillRegistry.from_directory(tmp_path)

    references.rename(skill_dir / "scripts")
    with pytest.raises(ValueError, match="unsupported"):
        AnalysisSkillRegistry.from_directory(tmp_path)


def test_registry_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    document = _document("bad-skill").replace(
        "name: bad-skill", "name: bad-skill\nname: bad-skill"
    )
    _write_skill(tmp_path, "bad-skill", document)

    with pytest.raises(ValueError, match="YAML"):
        AnalysisSkillRegistry.from_directory(tmp_path)


def test_registry_rejects_duplicate_ids() -> None:
    skill = BUILTIN_ANALYSIS_SKILLS.get("video-review", AnalysisInputKind.VIDEO)
    assert skill is not None

    with pytest.raises(ValueError, match="duplicate"):
        AnalysisSkillRegistry((skill, skill))


def test_registry_rejects_skill_directory_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    _write_skill(target, "linked-skill")
    link = tmp_path / "linked-skill"
    try:
        link.symlink_to(target / "linked-skill", target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")

    with pytest.raises(ValueError, match="symlink"):
        AnalysisSkillRegistry.from_directory(tmp_path)


def test_registry_rejects_reference_symlinks(tmp_path: Path) -> None:
    document = _document(
        "linked-reference",
        references="  video-server-references: references/rules.md\n",
    )
    skill_dir = _write_skill(tmp_path, "linked-reference", document)
    references = skill_dir / "references"
    references.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    try:
        (references / "rules.md").symlink_to(outside)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")

    with pytest.raises(ValueError, match="missing analysis skill reference"):
        AnalysisSkillRegistry.from_directory(tmp_path)


def test_registry_compiles_project_shared_references(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "style.md").write_text("# Shared style", encoding="utf-8")
    document = _document(
        "shared-user",
        references="  video-server-references: shared/style.md\n",
    )
    _write_skill(tmp_path, "shared-user", document)
    _write_skill(tmp_path, "plain")

    registry = AnalysisSkillRegistry.from_directory(tmp_path)

    skill = registry.get("shared-user", AnalysisInputKind.VIDEO)
    assert skill is not None
    assert "# Reference: shared/style.md\n\n# Shared style" in skill.instructions
    plain = registry.get("plain", AnalysisInputKind.VIDEO)
    assert plain is not None and "Shared style" not in plain.instructions


def test_registry_rejects_missing_or_nested_shared_references(tmp_path: Path) -> None:
    for name, reference in (
        ("missing-shared", "shared/absent.md"),
        ("nested-shared", "shared/deeper/style.md"),
    ):
        document = _document(
            name, references=f"  video-server-references: {reference}\n"
        )
        root = tmp_path / name
        root.mkdir()
        _write_skill(root, name, document)
        with pytest.raises(ValueError, match="reference"):
            AnalysisSkillRegistry.from_directory(root)


def test_compiled_modules_stay_pinned_and_omit_execution_instructions():
    for kind in AnalysisInputKind:
        for skill in BUILTIN_ANALYSIS_SKILLS.list(kind):
            text = skill.instructions
            assert "# Source module: zh-copywriting-guidelines" in text
            assert "scripts/main.ts" not in text
            assert "## 输出与文件保护" not in text
            assert "## 争议" not in text
    screenplay = BUILTIN_ANALYSIS_SKILLS.get(
        "screenplay-analysis", AnalysisInputKind.SCREENPLAY
    )
    assert "# Source module: sw-story-structure" in screenplay.instructions
    assert "## 四、九节拍" not in screenplay.instructions


def test_builtin_skills_contain_no_off_topic_or_leaked_material() -> None:
    for input_kind in (AnalysisInputKind.VIDEO, AnalysisInputKind.SCREENPLAY):
        for skill in BUILTIN_ANALYSIS_SKILLS.list(input_kind):
            text = skill.instructions
            assert "marketingskills" not in text, skill.id
            assert "VibeReels" not in text and "Lanverse" not in text, skill.id
            assert "Shot 00" not in text, skill.id
            assert "Rule classification" not in text, skill.id


def test_every_vendored_module_file_is_registered_and_used() -> None:
    modules_root = SKILLS_ROOT / "modules"
    registered = {module.path for module in SOURCE_MODULES.values()}
    vendored = {
        path.relative_to(modules_root).as_posix()
        for path in modules_root.glob("*/*.md")
    }
    assert vendored == registered
    used: set[str] = set()
    for input_kind in (AnalysisInputKind.VIDEO, AnalysisInputKind.SCREENPLAY):
        for skill in BUILTIN_ANALYSIS_SKILLS.list(input_kind):
            used.update(
                module_id
                for module_id in SOURCE_MODULES
                if f"# Source module: {module_id}\n" in skill.instructions
            )
    assert used == set(SOURCE_MODULES)
