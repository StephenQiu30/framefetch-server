"""Private editorial decisions; plans never become reader-facing sections."""

import re
from typing import Annotated

from pydantic import Field, StringConstraints

from app.services.analysis.rules.content_document import ContentModel
from app.services.analysis_execution.content_functions import MaterialArguments

Sentence = Annotated[str, StringConstraints(min_length=1, max_length=2_000)]


class EditorialPlan(ContentModel):
    reader_question: Sentence
    angle: Sentence
    movement: Annotated[tuple[Sentence, ...], Field(max_length=8)]
    omit: Annotated[tuple[Sentence, ...], Field(max_length=12)]


class ContentPlan(EditorialPlan):
    material_refs: Annotated[
        tuple[MaterialArguments, ...], Field(min_length=1, max_length=88)
    ]


class VideoPlan(EditorialPlan):
    revisit_ms: Annotated[
        tuple[Annotated[int, Field(strict=True, ge=0)], ...], Field(max_length=24)
    ]


def has_stage(snapshot: str, stage: str) -> bool:
    return f"# {stage.capitalize()}\n" in snapshot


def stage_method(snapshot: str, stage: str) -> str:
    markers = list(
        re.finditer(
            r"^# (Source module: [a-z0-9-]+|Purpose|Plan|Draft|Review|"
            r"Reference: .+)\s*$",
            snapshot,
            re.MULTILINE,
        )
    )
    selected = []
    for index, marker in enumerate(markers):
        label = marker.group(1)
        end = markers[index + 1].start() if index + 1 < len(markers) else len(snapshot)
        if (
            label
            in {
                stage.capitalize(),
                "Purpose",
                "Source module: zh-copywriting-guidelines",
            }
            or label.startswith("Reference:")
            or (
                label.startswith("Source module:")
                and label
                not in {
                    "Source module: humanizer-zh",
                    "Source module: baoyu-article-title",
                }
            )
            or label
            == (
                "Source module: humanizer-zh"
                if stage == "review"
                else "Source module: baoyu-article-title"
            )
        ):
            selected.append(snapshot[marker.start() : end].strip())
    return "\n\n".join(selected)
