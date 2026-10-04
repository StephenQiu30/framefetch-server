"""Canonical owner-scoped content creation HTTP contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CreationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class CreationTaskStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    OUTCOME_UNKNOWN = "outcome_unknown"


class CreationBudget(CreationModel):
    max_calls: int = Field(default=4, ge=1, le=32)
    max_tokens: int = Field(default=16_000, ge=1, le=200_000)
    timeout_seconds: int = Field(default=600, ge=10, le=3_600)
    max_cost_minor: int | None = Field(default=None, ge=1, le=100_000_000)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def cost_pair(self) -> "CreationBudget":
        if (self.max_cost_minor is None) != (self.currency is None):
            raise ValueError("cost and currency must be provided together")
        return self


class CreationUsage(CreationModel):
    calls_reserved: int = Field(default=0, ge=0)
    calls_used: int = Field(default=0, ge=0)
    tokens_reserved: int = Field(default=0, ge=0)
    cost_minor_reserved: int = Field(default=0, ge=0)
    unknown_operations: int = Field(default=0, ge=0)


class CreationSkillResponse(CreationModel):
    id: str
    code: str
    name: str
    route: Literal["film", "article"]
    priority: Literal["P0", "P1", "P2"]
    execution_kind: Literal["model", "local", "media"]
    input_kinds: tuple[str, ...]
    export_formats: tuple[str, ...]
    method_version: str
    method_sha256: str
    available: bool
    limitations: tuple[str, ...] = ()


class CreationProjectCreateRequest(CreationModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)


class CreationProjectResponse(CreationProjectCreateRequest):
    id: UUID
    created_at: datetime
    updated_at: datetime


MaterialKind = Literal["text", "screenplay", "video", "subtitle", "image", "reference"]


class CreationMaterialCreateRequest(CreationModel):
    project_id: UUID | None = None
    source_revision_id: UUID | None = None
    kind: MaterialKind
    title: str = Field(min_length=1, max_length=200)
    text: str | None = Field(default=None, max_length=30_000, repr=False)
    data: dict[str, Any] = Field(default_factory=dict)
    artifact_id: UUID | None = None
    download_id: UUID | None = None
    document_id: UUID | None = None
    document_filename: str | None = Field(default=None, min_length=1, max_length=200)
    document_data_base64: str | None = Field(
        default=None, max_length=14_000_000, repr=False
    )
    source_url: str | None = Field(default=None, max_length=2_048)
    image_data_base64: str | None = Field(
        default=None, max_length=14_000_000, repr=False
    )
    rights_statement: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def bounded_material(self) -> "CreationMaterialCreateRequest":
        if self.artifact_id is not None and self.download_id is not None:
            raise ValueError("choose an artifact or download, not both")
        if self.kind == "video" and not (self.artifact_id or self.download_id):
            raise ValueError("video requires a verified owned media artifact")
        if self.kind == "image" and not self.image_data_base64:
            raise ValueError("image requires an actual image file")
        if self.kind != "image" and self.image_data_base64 is not None:
            raise ValueError("image bytes only belong to image materials")
        if self.kind != "video" and (self.artifact_id or self.download_id):
            raise ValueError("media artifact only belongs to video materials")
        if (
            self.kind not in {"video", "image"}
            and not (self.text and self.text.strip())
            and self.document_id is None
            and self.source_url is None
            and self.source_revision_id is None
            and self.document_data_base64 is None
        ):
            raise ValueError("material requires readable text or an owned source")
        if self.source_url is not None and self.kind != "reference":
            raise ValueError("URL only belongs to a reference material")
        if (self.document_filename is None) != (self.document_data_base64 is None):
            raise ValueError("document filename and bytes are required together")
        if self.document_data_base64 is not None and (
            self.kind in {"video", "image"}
            or self.source_revision_id is not None
            or self.document_id is not None
            or self.source_url is not None
        ):
            raise ValueError("document upload must be a single text source")
        if self.source_revision_id is not None and (
            self.kind in {"video", "image"}
            or self.document_id is not None
            or self.source_url is not None
        ):
            raise ValueError("a confirmed result is a single text source")
        return self


class CreationRevisionResponse(CreationModel):
    id: UUID
    number: int
    parent_revision_id: UUID | None
    text: str
    data: dict[str, Any]
    sha256: str
    confirmed: bool
    created_at: datetime


class CreationRevisionSaveRequest(CreationModel):
    expected_revision_id: UUID
    text: str = Field(max_length=100_000, repr=False)
    data: dict[str, Any] = Field(default_factory=dict)


class CreationConfirmRequest(CreationModel):
    expected_revision_id: UUID


class CreationMaterialResponse(CreationModel):
    id: UUID
    project_id: UUID | None
    source_revision_id: UUID | None = None
    kind: MaterialKind
    title: str
    rights_statement: str
    artifact_id: UUID | None
    document_id: UUID | None
    source_url: str | None
    current_revision: CreationRevisionResponse
    created_at: datetime
    updated_at: datetime


class CreationTaskCreateRequest(CreationModel):
    project_id: UUID | None = None
    skill_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9-]+$")
    material_revision_ids: tuple[UUID, ...] = Field(min_length=1, max_length=28)
    options: dict[str, Any] = Field(default_factory=dict)
    budget: CreationBudget = Field(default_factory=CreationBudget)
    output_language: Literal["zh-CN"] = "zh-CN"

    @model_validator(mode="after")
    def unique_materials(self) -> "CreationTaskCreateRequest":
        if len(set(self.material_revision_ids)) != len(self.material_revision_ids):
            raise ValueError("material revisions must be unique")
        return self


class CreationTaskResponse(CreationModel):
    id: UUID
    project_id: UUID | None
    skill_id: str
    status: CreationTaskStatus
    material_revision_ids: tuple[UUID, ...]
    options: dict[str, Any]
    budget: CreationBudget
    usage: CreationUsage
    output_language: str
    attempt: int
    revision: CreationRevisionResponse | None
    stale: bool
    limitations: tuple[str, ...]
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class CreationRetryRequest(CreationModel):
    acknowledge_unknown_cost: bool = False
