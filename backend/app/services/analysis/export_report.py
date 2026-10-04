from __future__ import annotations

import hashlib
from uuid import UUID

from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
)
from app.services.analysis.get_analysis import GetAnalysis
from app.services.analysis.models import AnalysisReportFile, AnalysisStoredReportFile
from app.services.analysis.ports import AnalysisReportObjectReader, AnalysisRepository

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
MARKDOWN_MEDIA_TYPE = "text/markdown; charset=utf-8"


class ExportAnalysisReport:
    def __init__(
        self,
        get_analysis: GetAnalysis,
        repository: AnalysisRepository,
        object_reader: AnalysisReportObjectReader,
    ) -> None:
        self._get_analysis = get_analysis
        self._repository = repository
        self._object_reader = object_reader

    async def __call__(self, job_id: UUID, owner_hash: str) -> AnalysisReportFile:
        await self._get_analysis(job_id, owner_hash)
        stored = await self._repository.get_current_report_file(job_id, "docx")
        if stored is None:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.REPORT_NOT_READY
            )
        return AnalysisReportFile(
            content=await _read_verified(self._object_reader, stored),
            filename=f"analysis-report-{job_id}.docx",
            media_type=stored.media_type,
        )


class ExportAnalysisMarkdown:
    def __init__(
        self,
        get_analysis: GetAnalysis,
        repository: AnalysisRepository,
        object_reader: AnalysisReportObjectReader,
    ) -> None:
        self._get_analysis = get_analysis
        self._repository = repository
        self._object_reader = object_reader

    async def __call__(self, job_id: UUID, owner_hash: str) -> AnalysisReportFile:
        await self._get_analysis(job_id, owner_hash)
        stored = await self._repository.get_current_report_file(job_id, "markdown")
        if stored is None:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.REPORT_NOT_READY
            )
        return AnalysisReportFile(
            content=await _read_verified(self._object_reader, stored),
            filename=f"analysis-report-{job_id}.md",
            media_type=stored.media_type,
        )


async def _read_verified(
    reader: AnalysisReportObjectReader, stored: AnalysisStoredReportFile
) -> bytes:
    try:
        content = await reader.read(stored.object_key)
    except Exception as exc:
        raise AnalysisApplicationError(
            AnalysisApplicationErrorCode.REPORT_UNAVAILABLE
        ) from exc
    if (
        len(content) != stored.size_bytes
        or hashlib.sha256(content).hexdigest() != stored.sha256
    ):
        raise AnalysisApplicationError(AnalysisApplicationErrorCode.REPORT_UNAVAILABLE)
    return content
