from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import StrictModel
from app.schemas.download_intents import (
    IntentFailureResponse,
    IntentHistoryItemResponse,
    intent_resolution_state,
)
from app.services.analysis.rules.enums import (
    AnalysisErrorCode,
    AnalysisResultContract,
    AnalysisStage,
    AnalysisStatus,
)
from app.services.downloads.intent_models import IntentStatus
from app.services.history_records import (
    HistoryAvailability,
    HistoryRecordCursor,
    HistoryRecordKind,
    HistoryRecordPage,
    HistoryRecordSnapshot,
    HistoryStatusGroup,
    history_status_group,
)
from app.services.imports.rules.enums import ImportStatus


class HistoryRecordCursorResponse(StrictModel):
    created_at: datetime
    record_type: HistoryRecordKind
    id: UUID

    @classmethod
    def from_cursor(cls, cursor: HistoryRecordCursor) -> "HistoryRecordCursorResponse":
        return cls(
            created_at=cursor.created_at,
            record_type=cursor.record_type,
            id=cursor.id,
        )


class HistoryRecordSummary(StrictModel):
    updated_at: datetime
    status_group: HistoryStatusGroup
    source_availability: HistoryAvailability
    result_availability: HistoryAvailability


class ParseHistoryRecordResponse(IntentHistoryItemResponse, HistoryRecordSummary):
    record_type: Literal["parse"]


class AnalysisHistoryRecordResponse(HistoryRecordSummary):
    record_type: Literal["video_analysis", "screenplay_analysis"]
    document_id: UUID | None
    artifact_id: UUID | None
    output_language: str
    result_contract: AnalysisResultContract
    current_run_no: int
    cancel_requested_at: datetime | None
    version: int
    allowed_actions: list[Literal["view", "retry", "cancel", "delete"]]
    action_unavailable_reason: str | None

    id: UUID
    download_id: UUID | None
    title: str
    skill_id: str
    created_at: datetime
    status: AnalysisStatus
    progress: int
    stage: AnalysisStage | None
    error_code: AnalysisErrorCode | None


class VideoAnalysisHistoryRecordResponse(AnalysisHistoryRecordResponse):
    record_type: Literal["video_analysis"]


class ScreenplayAnalysisHistoryRecordResponse(AnalysisHistoryRecordResponse):
    record_type: Literal["screenplay_analysis"]


class DocumentParseHistoryRecordResponse(HistoryRecordSummary):
    record_type: Literal["document_parse"]
    id: UUID
    document_id: UUID
    title: str
    status: ImportStatus
    source_format: str
    created_at: datetime
    version: int
    error_code: str | None


HistoryRecordItemResponse = Annotated[
    ParseHistoryRecordResponse
    | VideoAnalysisHistoryRecordResponse
    | ScreenplayAnalysisHistoryRecordResponse
    | DocumentParseHistoryRecordResponse,
    Field(discriminator="record_type"),
]


class HistoryRecordPageResponse(StrictModel):
    items: list[HistoryRecordItemResponse]
    next_cursor: HistoryRecordCursorResponse | None

    @classmethod
    def from_page(cls, page: HistoryRecordPage) -> "HistoryRecordPageResponse":
        items: list[HistoryRecordItemResponse] = []
        for item in page.items:
            if item.record_type is HistoryRecordKind.PARSE:
                items.append(_parse_item(item))
            elif item.record_type is HistoryRecordKind.DOCUMENT_PARSE:
                items.append(
                    DocumentParseHistoryRecordResponse(
                        **_summary(item),
                        record_type="document_parse",
                        id=item.id,
                        document_id=item.id,
                        title=item.title or "剧本文档",
                        status=ImportStatus(item.status),
                        source_format=item.source_format or "unknown",
                        created_at=item.created_at,
                        version=item.version or 0,
                        error_code=item.error_code,
                    )
                )
            else:
                items.append(_analysis_item(item))
        return cls(
            items=items,
            next_cursor=(
                None
                if page.next_cursor is None
                else HistoryRecordCursorResponse.from_cursor(page.next_cursor)
            ),
        )


def _parse_item(item: HistoryRecordSnapshot) -> ParseHistoryRecordResponse:
    if item.version is None or item.deadline is None:
        raise ValueError("parse history record is incomplete")
    phase, action = intent_resolution_state(
        IntentStatus(item.status), item.latest_failure
    )
    return ParseHistoryRecordResponse(
        **_summary(item),
        record_type="parse",
        id=item.id,
        version=item.version,
        status=IntentStatus(item.status),
        reason_code=item.reason_code,
        phase=phase,
        next_action=action,
        failure=None
        if item.latest_failure is None
        else IntentFailureResponse.from_failure(item.latest_failure),
        retry_at=item.retry_at,
        deadline=item.deadline,
        inspection_id=item.inspection_id,
        job_id=item.job_id,
        created_at=item.created_at,
        title=item.title,
    )


def _analysis_item(
    item: HistoryRecordSnapshot,
) -> VideoAnalysisHistoryRecordResponse | ScreenplayAnalysisHistoryRecordResponse:
    if item.title is None or item.skill_id is None or item.progress is None:
        raise ValueError("video analysis history record is incomplete")
    response = (
        VideoAnalysisHistoryRecordResponse
        if item.record_type is HistoryRecordKind.VIDEO_ANALYSIS
        else ScreenplayAnalysisHistoryRecordResponse
    )
    return response.model_validate(
        dict(
            **_summary(item),
            record_type="video_analysis"
            if item.record_type is HistoryRecordKind.VIDEO_ANALYSIS
            else "screenplay_analysis",
            allowed_actions=["view", "delete"]
            + (
                ["cancel"]
                if item.status in {"queued", "running", "retry_wait"}
                else ["retry"]
                if item.source_availability is HistoryAvailability.AVAILABLE
                else []
            ),
            action_unavailable_reason="源文件不可用，无法重新执行。"
            if item.source_availability is HistoryAvailability.UNAVAILABLE
            else None,
            document_id=item.document_id,
            artifact_id=item.artifact_id,
            output_language=item.output_language or "und",
            result_contract=AnalysisResultContract(
                item.result_contract or "video-visual-analysis"
            ),
            current_run_no=item.current_run_no or 1,
            cancel_requested_at=item.cancel_requested_at,
            version=item.version or 0,
            id=item.id,
            download_id=item.download_id,
            title=item.title,
            skill_id=item.skill_id,
            created_at=item.created_at,
            status=AnalysisStatus(item.status),
            progress=item.progress,
            stage=None if item.stage is None else AnalysisStage(item.stage),
            error_code=(
                None if item.error_code is None else AnalysisErrorCode(item.error_code)
            ),
        )
    )


def _summary(item: HistoryRecordSnapshot) -> dict[str, Any]:
    return dict(
        updated_at=item.updated_at or item.created_at,
        status_group=history_status_group(item.status),
        source_availability=item.source_availability,
        result_availability=item.result_availability,
    )


class AnalysisRunHistoryResponse(StrictModel):
    id: UUID
    run_no: int
    trigger: str
    status: AnalysisStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: AnalysisErrorCode | None


class AnalysisRunHistoryPageResponse(StrictModel):
    items: list[AnalysisRunHistoryResponse]
    next_before_run_no: int | None
