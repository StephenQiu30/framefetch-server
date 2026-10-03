"""Finite content, immutable source snapshots and independent editorial review.

These models are also the public content contract. There is no second copy of
the same DTO in schemas; storage and adapters validate this one definition.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12_000)
]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,63}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
DocumentType = Literal["article", "post", "guide"]


class ContentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContentMaterial(ContentModel):
    id: Identifier
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    text: Annotated[str, StringConstraints(min_length=1, max_length=40_000)] = Field(
        repr=False
    )
    role: Literal["source", "author_style"] = "source"

    @model_validator(mode="after")
    def readable(self) -> ContentMaterial:
        if not self.text.strip() or "\x00" in self.text:
            raise ValueError("material must contain readable text")
        return self


class ContentBrief(ContentModel):
    document_type: DocumentType
    audience: Annotated[str, StringConstraints(min_length=1, max_length=400)] = (
        "对主题感兴趣的读者"
    )
    purpose: Annotated[str, StringConstraints(min_length=1, max_length=2_000)]
    voice: Annotated[str, StringConstraints(min_length=1, max_length=800)] = (
        "具体、自然，保留作者表达"
    )


class ContentSourceSet(ContentModel):
    materials: Annotated[tuple[ContentMaterial, ...], Field(min_length=1, max_length=8)]
    brief: ContentBrief

    @model_validator(mode="after")
    def bounded(self) -> ContentSourceSet:
        if len({item.id for item in self.materials}) != len(self.materials):
            raise ValueError("material IDs must be unique")
        if not any(item.role == "source" for item in self.materials):
            raise ValueError("at least one factual source is required")
        if sum(len(item.text.encode("utf-8")) for item in self.materials) > 160_000:
            raise ValueError("source set exceeds its byte limit")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()

    def segments(self) -> dict[str, tuple[str, ...]]:
        # Preserve original characters and line endings for exact quotations.
        return {
            item.id: tuple(
                item.text[i : i + 2_000] for i in range(0, len(item.text), 2_000)
            )
            for item in self.materials
        }

    def read_segment(self, material_id: str, segment_id: str) -> str:
        material = self.segments().get(material_id)
        if material is None or not segment_id.startswith("segment-"):
            raise ValueError("unknown material segment")
        suffix = segment_id.removeprefix("segment-")
        if not suffix.isdecimal() or segment_id != f"segment-{int(suffix):03d}":
            raise ValueError("invalid segment ID")
        index = int(suffix)
        if not 0 <= index < len(material):
            raise ValueError("unknown material segment")
        return material[index]


class ParagraphBlock(ContentModel):
    id: Identifier
    type: Literal["paragraph"]
    text: Text


class HeadingBlock(ContentModel):
    id: Identifier
    type: Literal["heading"]
    level: Literal[2, 3]
    text: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class ListBlock(ContentModel):
    id: Identifier
    type: Literal["list"]
    ordered: bool = Field(strict=True)
    items: Annotated[tuple[Text, ...], Field(min_length=1, max_length=30)]


class QuoteBlock(ContentModel):
    id: Identifier
    type: Literal["quote"]
    text: Text


ContentBlock = Annotated[
    ParagraphBlock | HeadingBlock | ListBlock | QuoteBlock, Field(discriminator="type")
]


class ContentCitation(ContentModel):
    block_id: Identifier
    material_id: Identifier
    segment_id: Annotated[str, StringConstraints(pattern=r"^segment-[0-9]{3}$")]
    quote: Annotated[str, StringConstraints(min_length=1, max_length=2_000)]


class ContentDraft(ContentModel):
    document_type: DocumentType
    language: Literal["zh-CN", "en-US"]
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None
    blocks: Annotated[tuple[ContentBlock, ...], Field(min_length=1, max_length=120)]
    evidence_index: Annotated[tuple[ContentCitation, ...], Field(max_length=200)]

    @model_validator(mode="after")
    def unique_blocks(self) -> ContentDraft:
        if len({block.id for block in self.blocks}) != len(self.blocks):
            raise ValueError("block IDs must be unique")
        if not any(block.type != "heading" for block in self.blocks):
            raise ValueError("content needs a body")
        if self.document_type != "post" and self.title is None:
            raise ValueError("article and guide require a title")
        if len(self.model_dump_json().encode()) > 200_000:
            raise ValueError("content exceeds its byte limit")
        return self

    def validate_sources(self, sources: ContentSourceSet) -> None:
        if self.document_type != sources.brief.document_type:
            raise ValueError("document type differs from brief")
        ids = {block.id for block in self.blocks}
        factual_ids = {item.id for item in sources.materials if item.role == "source"}
        for citation in self.evidence_index:
            if citation.block_id not in ids or citation.material_id not in factual_ids:
                raise ValueError("citation is outside this content or its sources")
            span = sources.read_segment(citation.material_id, citation.segment_id)
            if citation.quote not in span:
                raise ValueError("citation quote differs from the original material")


class ContentFinding(ContentModel):
    block_id: Identifier
    severity: Literal["blocking", "major", "minor"]
    category: Literal["fact", "purpose", "structure", "expression", "missing_material"]
    problem: Annotated[str, StringConstraints(min_length=1, max_length=1_000)]
    correction: Annotated[str, StringConstraints(min_length=1, max_length=1_000)]


class ContentReview(ContentModel):
    needs_material: bool = Field(strict=True)
    findings: Annotated[tuple[ContentFinding, ...], Field(max_length=30)]

    def validate_locations(self, draft: ContentDraft) -> None:
        valid = {block.id for block in draft.blocks} | {"title"}
        if any(item.block_id not in valid for item in self.findings):
            raise ValueError("review refers to a nonexistent block")

    @property
    def passed(self) -> bool:
        return not self.needs_material and not any(
            item.severity in {"blocking", "major"} for item in self.findings
        )


class ContentDocumentResult(ContentDraft):
    kind: Literal["content_document"]
    source_set_ref: Digest
    review_status: Literal["passed", "needs_review", "needs_material"]
    review_history: Annotated[tuple[ContentReview, ...], Field(max_length=2)]

    @model_validator(mode="after")
    def coherent_review(self) -> ContentDocumentResult:
        if not self.review_history:
            raise ValueError("a generated document requires an independent review")
        latest = self.review_history[-1]
        expected = (
            "needs_material"
            if latest.needs_material
            else "passed"
            if latest.passed
            else "needs_review"
        )
        if self.review_status != expected:
            raise ValueError("review status differs from findings")
        latest.validate_locations(self)
        return self


def content_schema(model: type[ContentModel]) -> dict[str, object]:
    """Require every field for model output; public models keep their defaults."""
    schema = model.model_json_schema()

    def require(value: object) -> None:
        if isinstance(value, dict):
            value.pop("default", None)
            value.pop("discriminator", None)
            if "oneOf" in value:
                value["anyOf"] = value.pop("oneOf")
            if value.get("type") == "object":
                value["required"] = list(value.get("properties", {}))
                value["additionalProperties"] = False
            for child in tuple(value.values()):
                require(child)
        elif isinstance(value, list):
            for child in value:
                require(child)

    require(schema)
    return schema
