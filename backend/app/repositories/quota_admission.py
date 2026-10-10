"""Atomic per-user business quotas in the caller transaction."""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quota import ResourceAdmissionRow
from app.repositories.owner_lock import lock_owner
from app.repositories.quota_queries import ACTIVE_USAGE, STORED_BYTES
from app.services.quotas import (
    DEFAULT_USER_QUOTA,
    QuotaExceeded,
    QuotaPolicy,
    UserQuota,
)

AdmissionKind = Literal[
    "download", "media_import", "document_import", "analysis", "inspection", "watermark"
]


async def lock_admission(session: AsyncSession, owner_hash: str) -> None:
    # User quota remains transactional. Global throughput is controlled by
    # RabbitMQ prefetch and bounded worker concurrency, not an API admission lock.
    await lock_owner(session, owner_hash)


async def ensure_active_capacity(
    session: AsyncSession, policy: QuotaPolicy, owner_hash: str
) -> int:
    """Check one additional active operation and return current reserved bytes.

    The caller holds the owner admission lock and has applied account policy.
    Existing intents use this check without a second daily reservation.
    """
    active = (
        await session.execute(
            ACTIVE_USAGE,
            {
                "owner": owner_hash,
                "download_bytes": policy.download_bytes,
                "document_bytes": policy.document_normalized_bytes,
                "report_bytes": policy.report_bytes,
                "thumbnail_bytes": policy.thumbnail_bytes,
            },
        )
    ).one()
    if active.owner_active >= policy.max_active_per_owner:
        raise QuotaExceeded("active_task_quota_exceeded")
    return int(active.reserved)


async def reserve(
    session: AsyncSession,
    policy: QuotaPolicy,
    *,
    owner_hash: str,
    resource_id: UUID,
    kind: AdmissionKind,
    now: datetime,
    size_bytes: int | None = None,
    analysis_attempts: int = 0,
    quota: UserQuota = DEFAULT_USER_QUOTA,
) -> None:
    """Reserve a user budget after replay and source validation.

    Administrators and explicitly exempt users bypass account-scoped budgets.
    """
    if quota.exempt:
        return
    policy = quota.apply(policy)
    reserved = {
        "inspection": 0,
        "watermark": size_bytes or 0,
        "download": policy.download_bytes + policy.thumbnail_bytes,
        "media_import": (size_bytes or 0) + policy.thumbnail_bytes,
        "document_import": (size_bytes or 0) + policy.document_normalized_bytes,
        "analysis": policy.report_bytes,
    }[kind]
    parameters = {
        "owner": owner_hash,
        "download_bytes": policy.download_bytes,
        "document_bytes": policy.document_normalized_bytes,
        "report_bytes": policy.report_bytes,
        "thumbnail_bytes": policy.thumbnail_bytes,
    }
    active_reserved = await ensure_active_capacity(session, policy, owner_hash)
    daily = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(ResourceAdmissionRow.reserved_bytes), 0),
                func.coalesce(func.sum(ResourceAdmissionRow.analysis_attempts), 0),
            ).where(
                ResourceAdmissionRow.owner_hash == owner_hash,
                ResourceAdmissionRow.created_at > now - timedelta(days=1),
            )
        )
    ).one()
    for used, requested, maximum, code in (
        (daily[0], 1, policy.daily_tasks, "daily_task_quota_exceeded"),
        (daily[1], reserved, policy.daily_bytes, "daily_byte_quota_exceeded"),
        (
            daily[2],
            analysis_attempts,
            policy.daily_analysis_attempts,
            "analysis_budget_exceeded",
        ),
    ):
        if used + requested > maximum:
            raise QuotaExceeded(code, retry_after=86400)
    stored = int(await session.scalar(STORED_BYTES, parameters) or 0)
    if stored + active_reserved + reserved > policy.storage_bytes:
        raise QuotaExceeded("storage_quota_exceeded")
    session.add(
        ResourceAdmissionRow(
            id=resource_id,
            owner_hash=owner_hash,
            kind=kind,
            reserved_bytes=reserved,
            analysis_attempts=analysis_attempts,
            created_at=now,
        )
    )
