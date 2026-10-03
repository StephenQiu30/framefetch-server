"""Deterministic Markdown/DOCX publication to private object storage."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Protocol

from app.integrations.analysis_report_docx import PythonDocxAnalysisReportRenderer
from app.integrations.object_storage import MinioObjectStorage
from app.repositories.analysis.report_repository import (
    ReportObject,
    SqlAlchemyAnalysisReportRepository,
)
from app.workers.report.message import ReportRequested

MARKDOWN_TYPE = "text/markdown; charset=utf-8"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ReportSizeExceeded(Exception):
    pass


class Clock(Protocol):
    def __call__(self) -> datetime: ...


class ReportPublisher:
    def __init__(
        self,
        repository: SqlAlchemyAnalysisReportRepository,
        storage: MinioObjectStorage,
        renderer: PythonDocxAnalysisReportRenderer,
        *,
        bucket: str,
        worker_id: str,
        clock: Clock,
        max_bytes: int = 16 * 1024**2,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._renderer = renderer
        self._bucket = bucket
        self._worker_id = worker_id
        self._clock = clock
        self._max_bytes = max_bytes

    async def execute(self, requested: ReportRequested) -> bool:
        now: datetime = self._clock()
        publication = await self._repository.claim(
            report_id=requested.report_id,
            job_id=requested.job_id,
            run_id=requested.run_id,
            expected_version=requested.version,
            worker_id=self._worker_id,
            now=now,
            lease_for=timedelta(minutes=5),
        )
        if publication is None:
            return True
        try:
            markdown = publication.markdown.encode("utf-8")
            if hashlib.sha256(markdown).hexdigest() != publication.markdown_sha256:
                raise RuntimeError("canonical Markdown hash mismatch")
            docx = self._renderer.render(
                publication.markdown, result_kind=publication.result_kind
            )
            if len(markdown) + len(docx) > self._max_bytes:
                raise ReportSizeExceeded("report exceeds publication byte budget")
            prefix = (
                f"analyses/{publication.job_id}/runs/{publication.run_no}/"
                f"reports/{publication.id}"
            )
            objects = (
                await self._ensure(
                    "markdown", f"{prefix}/report.md", markdown, MARKDOWN_TYPE
                ),
                await self._ensure("docx", f"{prefix}/report.docx", docx, DOCX_TYPE),
            )
            await self._repository.complete(
                publication, self._worker_id, objects, self._clock()
            )
            return True
        except ReportSizeExceeded:
            await self._repository.fail(
                publication.id,
                self._worker_id,
                "report_size_exceeded",
                self._clock(),
                terminal=True,
            )
            return True
        except Exception as error:
            await self._repository.fail(
                publication.id, self._worker_id, type(error).__name__, self._clock()
            )
            return False

    async def _ensure(
        self, report_format: str, key: str, content: bytes, media_type: str
    ) -> ReportObject:
        digest = hashlib.sha256(content).hexdigest()
        current = await self._storage.stat(key)
        if current is None:
            await self._storage.upload_bytes(key, content, media_type, digest)
            current = await self._storage.stat(key)
        if current is None or (current.size_bytes, current.sha256) != (
            len(content),
            digest,
        ):
            raise RuntimeError("stored report object conflicts")
        return ReportObject(
            format=report_format,
            bucket=self._bucket,
            object_key=key,
            content_type=media_type,
            size_bytes=len(content),
            sha256=digest,
        )
