"""Fixed inputs and evidence-bounded results of built-in Skills."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class SkillTextEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: Literal["primary", "secondary"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=1000)
    claim: str = Field(min_length=1, max_length=2000)
    status: Literal["observation", "inference", "suggestion", "unverified"]


class SkillMediaEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: Literal["primary", "secondary"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    frame_id: str = Field(min_length=1, max_length=100)
    frame_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    timestamp_ms: int = Field(ge=0)
    claim: str = Field(min_length=1, max_length=2000)
    status: Literal["observation", "inference", "suggestion", "unverified"]


class SkillReportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["skill_report"] = Field(json_schema_extra={"enum": ["skill_report"]})
    schema_version: Literal[1] = 1
    skill_id: str
    language: Literal["zh-CN"] = "zh-CN"
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(max_length=2000)
    body: str = Field(min_length=1, max_length=60000)
    evidence: tuple[SkillTextEvidence, ...] = Field(default=(), max_length=200)
    media_evidence: tuple[SkillMediaEvidence, ...] = Field(default=(), max_length=200)
    limitations: tuple[str, ...] = Field(default=(), max_length=100)
    data: dict[str, JsonValue] = Field(default_factory=dict)
