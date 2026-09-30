from __future__ import annotations

from pathlib import Path

import pytest
from app.integrations.analysis_skill_catalog import BuiltinAnalysisSkillCatalog
from app.services.analysis.rules.enums import AnalysisInputKind, AnalysisResultContract
from app.services.analysis.skills.registry import (
    BUILTIN_ANALYSIS_SKILLS,
    AnalysisSkillRegistry,
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
        "director-breakdown",
        "comprehensive",
        "video-to-article",
        "short-video-packaging",
        "visual-shots",
        "scene-extraction",
        "narrative-structure-review",
        "highlights",
        "editing-rhythm-review",
        "opening-hook-review",
        "continuity-quality-review",
        "asset-catalog",
    ]
    assert [skill.id for skill in screenplay] == [
        "screenplay-analysis",
        "screenplay-drama-review",
        "screenplay-character-review",
        "screenplay-scene-review",
        "screenplay-dialogue-review",
        "screenplay-structure-review",
        "screenplay-continuity-review",
        "screenplay-rewrite",
    ]
    assert {skill.result_contract for skill in video} == {
        AnalysisResultContract.VIDEO_VISUAL_ANALYSIS,
        AnalysisResultContract.VIDEO_ARTICLE,
        AnalysisResultContract.STRUCTURED_REPORT,
    }
    assert [skill.result_contract for skill in screenplay] == [
        *([AnalysisResultContract.SCREENPLAY_ANALYSIS] * 7),
        AnalysisResultContract.SCREENPLAY_REWRITE,
    ]


def test_builtin_resolution_compiles_allowlisted_reference_and_sha256() -> None:
    catalog = BuiltinAnalysisSkillCatalog()

    resolved = catalog.resolve("screenplay-analysis", AnalysisInputKind.SCREENPLAY)

    assert resolved is not None
    assert "# Source module: drama-review-method" in resolved.instructions
    assert "# Source module: sw-story-structure" in resolved.instructions
    assert "# Reference: references/output-contract.md" in resolved.instructions
    assert "完整场景调用必须返回以下字段" in resolved.instructions
    assert "汇总调用" in resolved.instructions
    assert "source_scene_id" in resolved.instructions
    assert len(resolved.instructions_sha256) == 64
    assert catalog.resolve("screenplay-analysis", AnalysisInputKind.VIDEO) is None
    assert BUILTIN_ANALYSIS_SKILLS.get("missing", AnalysisInputKind.VIDEO) is None


@pytest.mark.parametrize(
    ("skill_id", "reference_heading"),
    (
        ("director-breakdown", "# 导演拉片方法"),
        ("comprehensive", "# 综合分析证据规范"),
        ("video-to-article", "# 微信公众号文章编辑规范"),
        ("visual-shots", "# 分镜表字段规范"),
        ("scene-extraction", "# 场景边界与提炼规范"),
        ("narrative-structure-review", "# 成片叙事结构量表"),
        ("highlights", "# 高光候选量表"),
        ("editing-rhythm-review", "# 剪辑节奏量表"),
        ("opening-hook-review", "# 开场钩子审查量表"),
        ("continuity-quality-review", "# 连续性与成片 QA 量表"),
        ("asset-catalog", "# 资产身份与状态规范"),
    ),
)
def test_video_skills_compile_professional_reference_methods(
    skill_id: str, reference_heading: str
) -> None:
    skill = BUILTIN_ANALYSIS_SKILLS.get(skill_id, AnalysisInputKind.VIDEO)

    assert skill is not None
    assert reference_heading in skill.instructions


def test_builtin_skills_expose_the_current_production_boundary() -> None:
    expected_phrases = {
        "director-breakdown": ("镜头动机", "production_advice"),
        "comprehensive": ("观察、解释、建议", "video-visual-analysis"),
        "visual-shots": ("反向分镜表", "video-visual-analysis"),
        "scene-extraction": ("场景段落", "全部镜头"),
        "narrative-structure-review": ("结构主线", "不评价台词逻辑"),
        "highlights": ("同一量表", "主选"),
        "editing-rhythm-review": ("无目的快切", "固定秒数"),
        "opening-hook-review": ("0–3 秒", "不预测平台留存率"),
        "continuity-quality-review": ("交付前看片", "不声称完成逐帧"),
        "asset-catalog": ("AssetVersion", "资产身份候选"),
        "video-to-article": ("中心命题", "limitations"),
        "screenplay-analysis": ("汇总调用", "source_scene_id"),
        "screenplay-structure-review": ("连续性", "priority_revisions"),
        "screenplay-rewrite": ("不可变文本版本候选", "source_sha256"),
    }

    for skill_id, phrases in expected_phrases.items():
        skill = BUILTIN_ANALYSIS_SKILLS.get(
            skill_id,
            AnalysisInputKind.SCREENPLAY
            if skill_id.startswith("screenplay-")
            else AnalysisInputKind.VIDEO,
        )
        assert skill is not None
        assert all(phrase in skill.instructions for phrase in phrases), skill_id


@pytest.mark.parametrize(
    "skill_id",
    (
        "director-breakdown",
        "comprehensive",
        "visual-shots",
        "scene-extraction",
        "narrative-structure-review",
        "highlights",
        "editing-rhythm-review",
        "opening-hook-review",
        "continuity-quality-review",
        "asset-catalog",
    ),
)
def test_visual_skills_prevent_long_take_single_segment_collapse(
    skill_id: str,
) -> None:
    skill = BUILTIN_ANALYSIS_SKILLS.get(skill_id, AnalysisInputKind.VIDEO)

    assert skill is not None
    assert "transition_in=continuous" in skill.instructions
    assert "固定秒数" in skill.instructions or "固定时长" in skill.instructions


def test_article_and_screenplay_skills_preserve_stage_boundaries() -> None:
    article = BUILTIN_ANALYSIS_SKILLS.get("video-to-article", AnalysisInputKind.VIDEO)
    screenplay = BUILTIN_ANALYSIS_SKILLS.get(
        "screenplay-analysis", AnalysisInputKind.SCREENPLAY
    )
    structure = BUILTIN_ANALYSIS_SKILLS.get(
        "screenplay-structure-review", AnalysisInputKind.SCREENPLAY
    )
    rewrite = BUILTIN_ANALYSIS_SKILLS.get(
        "screenplay-rewrite", AnalysisInputKind.SCREENPLAY
    )

    assert article is not None
    assert "连续长镜头" in article.instructions
    assert "固定秒数" in article.instructions
    assert screenplay is not None and "镜头数量" in screenplay.instructions
    assert structure is not None and "镜头数量" in structure.instructions
    assert rewrite is not None and "新增场景或镜头" in rewrite.instructions


def test_opening_hook_review_preserves_visual_evidence_boundaries() -> None:
    skill = BUILTIN_ANALYSIS_SKILLS.get("opening-hook-review", AnalysisInputKind.VIDEO)

    assert skill is not None
    assert skill.result_contract is AnalysisResultContract.VIDEO_VISUAL_ANALYSIS
    assert "覆盖完整时间轴" in skill.instructions
    assert "0–3s" in skill.instructions
    assert "0–5s" in skill.instructions
    assert "0–15s" in skill.instructions
    assert "不评价开场台词、语速、音乐卡点" in skill.instructions
    assert "不表示停留、完播、点击、转化" in skill.instructions
    assert "真实 `shot.id`" in skill.instructions


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
    skill = BUILTIN_ANALYSIS_SKILLS.get("director-breakdown", AnalysisInputKind.VIDEO)
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


def test_every_builtin_skill_carries_the_writing_standard() -> None:
    for input_kind in (AnalysisInputKind.VIDEO, AnalysisInputKind.SCREENPLAY):
        for skill in BUILTIN_ANALYSIS_SKILLS.list(input_kind):
            text = skill.instructions
            assert "# Source module: zh-copywriting-guidelines" in text, skill.id
            if skill.id == "screenplay-rewrite":
                assert "# Source module: humanizer-zh" not in text
                continue
            assert "# Source module: humanizer-zh" in text, skill.id
            assert "# Reference: shared/report-writing.md" in text, skill.id
            assert "## 成稿写法" in text, skill.id
            assert "## 输出与文件保护" not in text, skill.id
            assert "## 争议" not in text, skill.id
            if input_kind is AnalysisInputKind.SCREENPLAY:
                assert "# Reference: shared/screenplay-coverage-writing.md" in text


@pytest.mark.parametrize(
    ("skill_id", "input_kind", "contract", "modules", "excluded"),
    [
        (
            "director-breakdown",
            AnalysisInputKind.VIDEO,
            AnalysisResultContract.VIDEO_VISUAL_ANALYSIS,
            (
                "drama-skills-short-drama-storyboard-shot-craft",
                "drama-skills-short-drama-storyboard-production-shot-grammar",
                "drama-skills-short-drama-storyboard-blocking-playbooks",
            ),
            "## 四、动作顺序交接（给视频提示词环节的输入）",
        ),
        (
            "editing-rhythm-review",
            AnalysisInputKind.VIDEO,
            AnalysisResultContract.VIDEO_VISUAL_ANALYSIS,
            (
                "drama-skills-short-drama-edit-cut-craft",
                "marketingskills-video-edit-anatomy",
            ),
            "## Step 1 —",
        ),
        (
            "continuity-quality-review",
            AnalysisInputKind.VIDEO,
            AnalysisResultContract.VIDEO_VISUAL_ANALYSIS,
            ("drama-skills-short-drama-storyboard-blocking-playbooks",),
            "## 5. 动态对象与竞赛",
        ),
        (
            "screenplay-structure-review",
            AnalysisInputKind.SCREENPLAY,
            AnalysisResultContract.SCREENPLAY_ANALYSIS,
            (
                "sw-story-structure",
                "sw-scene-craft",
                "screenwriting-skills-sw-premise-theme-skill",
                "screenwriting-skills-sw-truby-anatomy-skill",
            ),
            "## 十二、从想法到前提：工作流程",
        ),
        (
            "short-video-packaging",
            AnalysisInputKind.VIDEO,
            AnalysisResultContract.STRUCTURED_REPORT,
            (
                "marketingskills-social-short-form-video",
                "marketingskills-social-platforms",
            ),
            "## Posting Strategy",
        ),
    ],
)
def test_reviewed_product_skills_compile_pinned_methods_with_local_boundaries(
    skill_id: str,
    input_kind: AnalysisInputKind,
    contract: AnalysisResultContract,
    modules: tuple[str, ...],
    excluded: str,
) -> None:
    skill = BUILTIN_ANALYSIS_SKILLS.get(skill_id, input_kind)
    assert skill is not None and skill.result_contract is contract
    text = skill.instructions
    for module in modules:
        assert f"# Source module: {module}\nPinned source: https://github.com/" in text
    assert excluded not in text
    assert "## 引用方法的用法" in text
    assert text.rindex("# Source module:") < text.index("## 引用方法的用法")
    if input_kind is AnalysisInputKind.VIDEO:
        assert "当前没有可靠音频证据" in text
    else:
        assert "不得要求剧本套用固定步骤数或页码" in text
