from dataclasses import replace
from pathlib import Path

import pytest
from app.integrations.ai_cli.skill_resources import prepare_resource_policy
from app.integrations.ai_cli.workspace import prepare_job_files
from app.services.analysis.rules.enums import AnalysisInputKind
from app.services.analysis.skills.registry import BUILTIN_ANALYSIS_SKILLS
from app.services.analysis.skills.upstream_catalog import (
    UpstreamCatalog,
    frozen_packages,
)
from app.services.analysis_execution.editorial_plan import stage_method
from app.services.analysis_execution.models import VideoAnalysisRequest
from app.services.analysis_execution.monitor import request_digest
from app.services.analysis_execution.video_shots import ShotAnnotations
from pydantic import ValidationError


def test_article_stages_keep_every_full_upstream_entry_and_frozen_resource_policy(
    tmp_path,
):
    skill = BUILTIN_ANALYSIS_SKILLS.get("video-to-article", AnalysisInputKind.VIDEO)
    assert skill is not None
    catalog = UpstreamCatalog()
    entry = catalog.read_markdown("ecc", "skills/article-writing/SKILL.md")
    for stage in ("plan", "draft", "review"):
        method = stage_method(skill.instructions, stage)
        assert entry in method
        assert set(frozen_packages(method)) == {"reelbench", "ecc", "baoyu", "drama"}
        (tmp_path / "policy").mkdir(exist_ok=True)
        prepare_resource_policy(tmp_path, method)
        assert (tmp_path / "policy/upstream-resources.json").is_file()


def test_annotations_cannot_replace_machine_fields_or_add_instructions():
    annotation = {
        "id": "S01",
        "size": "none",
        "category": "text-card",
        "camera": "static",
        "frame": "深色背景上排列着文件备份教程文字。",
        "onscreenText": "备份",
        "audio": "",
        "rhythm": "setup",
        "rhythmNote": "画面说明后续备份操作所需的背景。",
    }
    assert ShotAnnotations.model_validate({"shots": [annotation]}).shots[0].id == "S01"
    for field in ("start", "end", "seconds", "motion", "script"):
        with pytest.raises(ValidationError):
            ShotAnnotations.model_validate({"shots": [{**annotation, field: 1}]})


def test_image_digest_is_bound_but_attempt_paths_are_not():
    request = VideoAnalysisRequest(
        artifact=Path("/first/input/video.bin"),
        workspace=Path("/first"),
        duration_ms=40000,
        size_bytes=1000,
        container="mp4",
        output_language="zh-CN",
        skill_id="video-shots",
        skill_instructions="frozen method",
        image_paths=(Path("/first/work/sheet-a01.jpg"),),
        image_digests=("a" * 64,),
    )
    assert request_digest(request) == request_digest(
        replace(
            request,
            workspace=Path("/second"),
            image_paths=(Path("/second/work/sheet-a01.jpg"),),
        )
    )
    assert request_digest(request) != request_digest(
        replace(request, image_digests=("b" * 64,))
    )


def test_image_integrity_is_checked_before_model_start(tmp_path):
    from app.integrations.ai_cli.errors import AnalysisCliError

    root = tmp_path / "job"
    (root / "input").mkdir(parents=True)
    (root / "work").mkdir()
    video = root / "input/video.bin"
    video.write_bytes(b"verified source")
    image = root / "work/sheet-a01.jpg"
    image.write_bytes(b"changed frame")
    request = VideoAnalysisRequest(
        artifact=video,
        workspace=root,
        duration_ms=40_000,
        size_bytes=15,
        container="mp4",
        output_language="zh-CN",
        skill_id="video-shots",
        skill_instructions="frozen method",
        image_paths=(image,),
        image_digests=("a" * 64,),
    )
    with pytest.raises(AnalysisCliError):
        prepare_job_files(request, {}, "fixed prompt")
