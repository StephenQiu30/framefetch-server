from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.analysis_results import (
    ANALYSIS_RESULT_RESPONSE_ADAPTER,
    AnalysisResultResponse,
)
from app.schemas.common import StrictModel
from app.services.analysis.models import AnalysisJobView
from app.services.analysis.rules.enums import (
    AnalysisErrorCode,
    AnalysisInputKind,
    AnalysisReportStatus,
    AnalysisResultContract,
    AnalysisStage,
    AnalysisStatus,
)


class AnalysisRequest(StrictModel):
    skill_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="由分析 Skill 清单提供的稳定任务标识。",
        examples=["video-review"],
    )
    output_language: str = Field(
        min_length=2,
        max_length=35,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$",
        description="结果语言；本项目支持 zh-CN 和 en-US。",
        examples=["zh-CN", "en-US"],
    )
    custom_prompt: str | None = Field(
        default=None,
        max_length=4000,
        description="可编辑的任务要求；不能覆盖来源、安全、工具或结果结构。",
    )

    @field_validator("custom_prompt")
    @classmethod
    def normalize_custom_prompt(cls, value: str | None) -> str | None:
        return None if value is None else value.strip() or None


class AnalysisSkillResponse(StrictModel):
    id: str
    display_name: str
    description: str
    default_prompt: str
    input_kinds: tuple[AnalysisInputKind, ...]
    result_contract: AnalysisResultContract


class AnalysisReportArtifactResponse(StrictModel):
    format: str
    media_type: str
    size_bytes: int
    sha256: str


class AnalysisReportResponse(StrictModel):
    id: UUID
    status: AnalysisReportStatus
    renderer_version: str
    content_sha256: str
    published_at: datetime | None
    artifacts: tuple[AnalysisReportArtifactResponse, ...]


class AnalysisResponse(StrictModel):
    id: UUID
    run_id: UUID
    run_no: int
    run_trigger: str
    version: int
    skill_id: str
    output_language: str
    input_kind: AnalysisInputKind
    result_contract: AnalysisResultContract
    status: AnalysisStatus
    stage: AnalysisStage | None
    progress: int
    attempt: int
    error_code: AnalysisErrorCode | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    result: AnalysisResultResponse | None
    report_markdown: str | None
    current_report_id: UUID | None
    report: AnalysisReportResponse | None

    @classmethod
    def from_view(cls, view: AnalysisJobView) -> AnalysisResponse:
        result = cls._public_result(view.result)
        if view.status is AnalysisStatus.SUCCEEDED and result is None:
            raise ValueError("succeeded analysis must have a result")
        return cls(
            id=view.id,
            run_id=view.run_id,
            run_no=view.run_no,
            run_trigger=view.run_trigger,
            version=view.version,
            skill_id=view.skill_id,
            output_language=view.output_language,
            input_kind=view.input_kind,
            result_contract=view.result_contract,
            status=view.status,
            stage=view.stage,
            progress=view.progress,
            attempt=view.attempt,
            error_code=view.error_code,
            created_at=view.created_at,
            updated_at=view.updated_at,
            finished_at=view.finished_at,
            result=result,
            report_markdown=(
                view.report.markdown
                if view.report is not None and view.report.id == view.current_report_id
                else None
            ),
            current_report_id=view.current_report_id,
            report=(
                None
                if view.report is None
                else AnalysisReportResponse(
                    id=view.report.id,
                    status=view.report.status,
                    renderer_version=view.report.renderer_version,
                    content_sha256=view.report.content_sha256,
                    published_at=view.report.published_at,
                    artifacts=tuple(
                        AnalysisReportArtifactResponse(
                            format=item.format,
                            media_type=item.media_type,
                            size_bytes=item.size_bytes,
                            sha256=item.sha256,
                        )
                        for item in view.report.artifacts
                    ),
                )
            ),
        )

    @staticmethod
    def _public_result(
        result: object | None,
    ) -> AnalysisResultResponse | None:
        if result is None:
            return None
        return ANALYSIS_RESULT_RESPONSE_ADAPTER.validate_python(result)
