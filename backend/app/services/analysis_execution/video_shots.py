"""Visual annotations are merged into measured shots; machine fields stay immutable."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from functools import partial
from typing import Annotated, Literal

from pydantic import Field

from app.services.analysis.models import AnalysisJobSnapshot
from app.services.analysis.rules.content_document import ContentModel, content_schema
from app.services.analysis.rules.enums import AnalysisStage
from app.services.analysis.rules.result_models import (
    AnalysisMedia,
    VideoArticleEvidence,
)
from app.services.analysis.rules.structured_report import (
    StructuredReportResult,
    StructuredReportSection,
)
from app.services.analysis_execution.models import VideoAnalysisRequest
from app.services.analysis_execution.monitor import AnalysisLeaseMonitor
from app.services.analysis_execution.native_video import MeasuredVideo, native_reports
from app.services.analysis_execution.ports import AnalyzerSelection


class ShotAnnotation(ContentModel):
    id: str = Field(pattern=r"^S[0-9]+$")
    size: Literal[
        "extreme-wide",
        "wide",
        "medium-wide",
        "medium",
        "medium-close",
        "close",
        "extreme-close",
        "none",
    ]
    category: Literal[
        "establishing",
        "subject",
        "dialogue",
        "insert",
        "pov",
        "empty",
        "product",
        "text-card",
        "transition",
        "archive",
    ]
    camera: Literal[
        "static",
        "push-in",
        "pull-out",
        "zoom-in",
        "zoom-out",
        "pan-left",
        "pan-right",
        "tilt-up",
        "tilt-down",
        "truck-left",
        "truck-right",
        "pedestal-up",
        "pedestal-down",
        "tracking",
        "arc",
        "whip-pan",
        "handheld",
        "shake",
        "rack-focus",
        "micro-push",
        "roll",
        "drone",
    ]
    frame: str = Field(min_length=12, max_length=400)
    onscreen_text: str = Field(alias="onscreenText", max_length=1200)
    audio: str = Field(max_length=1200)
    rhythm: Literal[
        "hook", "setup", "build", "beat", "turn", "payoff", "breath", "close"
    ]
    rhythm_note: str = Field(alias="rhythmNote", min_length=8, max_length=150)


class ShotAnnotations(ContentModel):
    shots: Annotated[tuple[ShotAnnotation, ...], Field(min_length=1, max_length=24)]


async def annotate_shots(
    job: AnalysisJobSnapshot,
    request: VideoAnalysisRequest,
    selection: AnalyzerSelection,
    monitor: AnalysisLeaseMonitor,
    media: AnalysisMedia,
    measured: MeasuredVideo,
) -> tuple[StructuredReportResult, str, bytes]:
    if not getattr(selection.analyzer, "supports_skill_images", False):
        from app.services.analysis_execution.errors import AnalysisExecutionError

        raise AnalysisExecutionError(
            "analysis_cli_unsupported", no_model_execution=True
        )
    shots = measured.document["shots"]
    schema = content_schema(ShotAnnotations)
    await monitor.bind_execution(
        {
            "method_sha256": job.skill_instructions_sha256,
            "source_sha256": job.input_sha256,
            "measurement": measured.document,
            "provider": selection.provider,
            "model": selection.model,
            "schema": schema,
            "max_model_calls": (len(shots) + 23) // 24,
        },
        deadline_for=timedelta(seconds=3600),
    )
    for start in range(0, len(shots), 24):
        batch = shots[start : start + 24]
        page = start // 24 + 1
        images = tuple(
            measured.directory / f"sheets/sheet-{pick}{page:02}.jpg"
            for pick in ("a", "b")
        )
        value = replace(
            request,
            stage=f"shots-{page:03}",
            image_paths=images,
            image_digests=tuple(
                hashlib.sha256(path.read_bytes()).hexdigest() for path in images
            ),
            measured_context=json.dumps(batch, ensure_ascii=False),
            schema_json=json.dumps(schema),
            stage_prompt=request.skill_instructions
            + (
                "\n只返回本批逐镜标注；图一为起手，图二为收尾，4列按镜号排列。"
                "不得返回或修改机器字段。人物用匿名可见描述。"
                "先读取上游 taxonomy，按其精确枚举填写；"
                "未建立 cast 时不使用 reaction 类别。"
            ),
        )

        def parse(
            payload: object, expected: tuple[str, ...] = tuple(s["id"] for s in batch)
        ) -> ShotAnnotations:
            result = ShotAnnotations.model_validate(payload)
            if tuple(s.id for s in result.shots) != expected:
                raise ValueError("annotation shot IDs differ from measured batch")
            return result

        annotations = await monitor.step(
            f"shots-{page:03}",
            value,
            partial(selection.analyzer.analyze, value),
            parse,
            stage=AnalysisStage.ANALYZING,
            progress=min(85, 25 + start * 60 // len(shots)),
        )
        for original, annotation in zip(batch, annotations.shots, strict=True):
            original.update(annotation.model_dump(exclude={"id"}, by_alias=True))
            original["subjects"] = []
    markdown, _html, bundle = await native_reports(measured)
    sections = tuple(
        StructuredReportSection(
            id=f"shots-{start:03}",
            heading=(
                f"{shots[start]['id']}–{shots[min(start + 11, len(shots) - 1)]['id']}"
            ),
            body="\n\n".join(
                f"{s['id']} · {s['start']}–{s['end']} s · "
                f"{s['size']} / {s['camera']} · motion {s['motion']}\n"
                f"{s['frame']}\n{s['rhythmNote']}"
                for s in shots[start : start + 12]
            ),
            items=(),
            evidence=tuple(
                VideoArticleEvidence(
                    round(s["start"] * 1000),
                    min(media.duration_ms, round(s["end"] * 1000)),
                    s["frame"],
                )
                for s in shots[start : start + 12]
            ),
        )
        for start in range(0, len(shots), 12)
    )
    result = StructuredReportResult(
        language=request.output_language,
        title=measured.document["title"],
        summary=(
            f"实测 {len(shots)} 个检测镜头；运动曲线、每镜两张关键帧及原生校验已完成。"
            if request.output_language == "zh-CN"
            else (
                f"Measured {len(shots)} detected shots, with motion curves, "
                "two frames per shot and native validation."
            )
        ),
        sections=sections,
        limitations=(
            (
                "自动检测切点不等于全部真实剪切已确认，软转场需人工复核。",
                "仅视觉取证，未核验声音；未建立人物身份索引。",
            )
            if request.output_language == "zh-CN"
            else (
                "Detected cuts require manual review, especially soft transitions.",
                "Visual evidence only; audio and identities remain unverified.",
            )
        ),
        media=media,
    )
    return result, markdown, bundle
