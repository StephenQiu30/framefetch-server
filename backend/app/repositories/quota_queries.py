"""Current retained bytes and reservations, including pending physical deletion."""

from enum import StrEnum

from sqlalchemy import text

from app.services.analysis.rules.enums import (
    AnalysisReportArtifactStatus,
    AnalysisReportStatus,
    AnalysisStatus,
)
from app.services.downloads.intent_models import ACTIVE_INTENT_STATUSES
from app.services.downloads.rules.enums import DownloadStatus
from app.services.imports.rules.enums import ImportStatus


def _sql_values(values: tuple[StrEnum, ...]) -> str:
    return ", ".join(f"'{value.value}'" for value in values)


_ACTIVE_DOWNLOAD_STATUSES = _sql_values(
    (DownloadStatus.QUEUED, DownloadStatus.RUNNING, DownloadStatus.RETRY_WAIT)
)
_ACTIVE_IMPORT_STATUSES = _sql_values((ImportStatus.UPLOADING, ImportStatus.VERIFYING))
_ACTIVE_ANALYSIS_STATUSES = _sql_values(
    (AnalysisStatus.QUEUED, AnalysisStatus.RUNNING, AnalysisStatus.RETRY_WAIT)
)
_PENDING_REPORT_STATUSES = _sql_values(
    (
        AnalysisReportStatus.PUBLISHING,
        AnalysisReportStatus.PUBLISH_FAILED,
        AnalysisReportStatus.DELETE_PENDING,
    )
)
_DELETED_REPORT_ARTIFACT_STATUS = AnalysisReportArtifactStatus.DELETED.value

# Import jobs already have a download projection and must be counted only once.
# Workers replace active reservations with bounded artifacts in one transaction.
ACTIVE_USAGE = text(f"""
WITH active AS (
    SELECT owner_hash, 2147483648 AS reserved_bytes FROM watermark_tasks
    WHERE status IN ('queued','running')
       OR (status IN ('failed','cancelled') AND object_key IS NOT NULL)
    UNION ALL
    SELECT owner_hash, 0 AS reserved_bytes FROM download_intents
    WHERE status IN ({_sql_values(ACTIVE_INTENT_STATUSES)})
    UNION ALL
    SELECT j.owner_hash, COALESCE(q.reserved_bytes,
        m.declared_size_bytes + :thumbnail_bytes,
        :download_bytes + :thumbnail_bytes) AS reserved_bytes
    FROM download_jobs j
    LEFT JOIN resource_admissions q ON q.id = j.id
    LEFT JOIN media_imports m ON m.id = j.id
    WHERE j.status IN ({_ACTIVE_DOWNLOAD_STATUSES})
    UNION ALL
    SELECT d.owner_hash, COALESCE(q.reserved_bytes,
        d.declared_size_bytes + :document_bytes)
    FROM documents d LEFT JOIN resource_admissions q ON q.id = d.id
    WHERE d.status IN ({_ACTIVE_IMPORT_STATUSES})
    UNION ALL
    SELECT j.owner_hash, COALESCE(q.reserved_bytes, :report_bytes)
    FROM analysis_jobs j
    LEFT JOIN resource_admissions q ON q.id = j.active_run_id
    WHERE j.status IN ({_ACTIVE_ANALYSIS_STATUSES})
    UNION ALL
    SELECT j.owner_hash, COALESCE(q.reserved_bytes, :report_bytes)
    FROM analysis_report_versions r
    JOIN analysis_jobs j ON j.id = r.job_id
    LEFT JOIN resource_admissions q ON q.id = r.run_id
    WHERE r.status IN ({_PENDING_REPORT_STATUSES})
      AND (j.status NOT IN ({_ACTIVE_ANALYSIS_STATUSES})
           OR j.active_run_id <> r.run_id)
      AND NOT EXISTS (SELECT 1 FROM analysis_report_artifacts a
                      WHERE a.report_id = r.id)
)
SELECT COUNT(*) FILTER (WHERE owner_hash = :owner) AS owner_active,
    COALESCE(SUM(reserved_bytes) FILTER (WHERE owner_hash = :owner), 0) AS reserved
FROM active
""")

# Download tombstones precede object deletion. Documents and all report versions
# remain charged until their physical cleanup records reach the deleted state.
STORED_BYTES = text(f"""
SELECT COALESCE(SUM(size_bytes), 0) FROM (
    SELECT size_bytes FROM watermark_tasks WHERE owner_hash = :owner
    UNION ALL
    SELECT a.size_bytes FROM artifacts a
    JOIN download_jobs j ON j.id = a.job_id WHERE j.owner_hash = :owner
    UNION ALL
    SELECT t.size_bytes FROM download_thumbnails t
    JOIN download_jobs j ON j.id = t.job_id WHERE j.owner_hash = :owner
    UNION ALL
    SELECT a.size_bytes FROM document_artifacts a
    JOIN documents d ON d.id = a.document_id
    WHERE d.owner_hash = :owner AND a.status <> 'deleted'
    UNION ALL
    SELECT a.size_bytes FROM analysis_report_artifacts a
    JOIN analysis_report_versions r ON r.id = a.report_id
    JOIN analysis_jobs j ON j.id = r.job_id
    WHERE j.owner_hash = :owner
      AND a.status <> '{_DELETED_REPORT_ARTIFACT_STATUS}'
) stored
""")
