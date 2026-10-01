"""Short PostgreSQL transactions own intent acceptance and result commits.

Network work happens between beginning and completing an operation,
never under a row lock.
"""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.download import DownloadJobRow
from app.models.download_intent import DownloadIntentRow
from app.models.media import MediaInspectionRow
from app.models.outbox import OutboxEventRow
from app.repositories.downloads.access_repository import cancel_job_row
from app.repositories.downloads.media_repository import insert_inspection
from app.repositories.errors import (
    IdempotencyConflict,
    RepositoryConflict,
    RepositoryNotFound,
)
from app.repositories.quota_admission import (
    ensure_active_capacity,
    lock_admission,
    reserve,
)
from app.services.downloads.inspection_models import EncryptedUrl, InspectionCreate
from app.services.downloads.intent_models import (
    RUNNING_INTENT_STATUSES,
    TERMINAL_INTENT_STATUSES,
    IntentCreate,
    IntentHistoryEntry,
    IntentHistoryPage,
    IntentOperation,
    IntentSnapshot,
    IntentStatus,
)
from app.services.downloads.validation import (
    media_kind_from_metadata,
    validate_idempotency_key,
    validate_now,
    validate_owner_hash,
)
from app.services.provider_failures import ProviderFailure
from app.services.provider_types import ExecutionContext
from app.services.quotas import DEFAULT_USER_QUOTA, QuotaPolicy, UserQuota

_RUNNING = tuple(status.value for status in RUNNING_INTENT_STATUSES)
_ACTIVE = (IntentStatus.QUEUED.value, *_RUNNING)
_TIMEOUT = timedelta(seconds=120)
PROVIDER_FAILURE = TypeAdapter(ProviderFailure)


class IntentRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        quota_policy: QuotaPolicy | None = None,
    ) -> None:
        self._sessions = sessions
        self._quota_policy = quota_policy or QuotaPolicy()

    async def accept(
        self,
        command: IntentCreate,
        *,
        now: datetime,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> IntentSnapshot:
        validate_now(now)
        validate_owner_hash(command.owner_hash)
        validate_idempotency_key(command.idempotency_key)
        if len(command.request_fingerprint) != 64:
            raise ValueError("invalid intent fingerprint")
        async with self._sessions() as session, session.begin():
            await lock_admission(session, command.owner_hash)
            existing = await session.scalar(
                select(DownloadIntentRow).where(
                    DownloadIntentRow.owner_hash == command.owner_hash,
                    DownloadIntentRow.idempotency_key == command.idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_fingerprint != command.request_fingerprint:
                    raise IdempotencyConflict("intent idempotency key already used")
                return _snapshot(existing)
            await reserve(
                session,
                self._quota_policy,
                owner_hash=command.owner_hash,
                resource_id=command.id,
                kind="inspection",
                now=now,
                quota=quota,
            )
            row = await session.scalar(
                insert(DownloadIntentRow)
                .values(
                    id=command.id,
                    owner_hash=command.owner_hash,
                    idempotency_key=command.idempotency_key,
                    request_fingerprint=command.request_fingerprint,
                    url_ciphertext=command.url.ciphertext,
                    url_nonce=command.url.nonce,
                    url_key_id=command.url.key_id,
                    deadline=now + _TIMEOUT,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(constraint="uq_download_intents_owner_key")
                .returning(DownloadIntentRow)
            )
            if row is None:
                row = await session.scalar(
                    select(DownloadIntentRow).where(
                        DownloadIntentRow.owner_hash == command.owner_hash,
                        DownloadIntentRow.idempotency_key == command.idempotency_key,
                    )
                )
                if row is None:
                    raise RepositoryConflict("intent disappeared during acceptance")
                if row.request_fingerprint != command.request_fingerprint:
                    raise IdempotencyConflict("intent idempotency key already used")
            else:
                session.add(_requested(row, now))
            # Context manager commits both records before returning to the caller.
            return _snapshot(row)

    async def get(
        self, intent_id: UUID, owner_hash: str, *, now: datetime | None = None
    ) -> IntentSnapshot:
        async with self._sessions() as session, session.begin():
            row = await self._owned(
                session, intent_id, owner_hash, lock=now is not None
            )
            if now is not None:
                _request_expiry(session, row, now)
            return _snapshot(row)

    async def get_by_key(
        self, idempotency_key: str, owner_hash: str, *, now: datetime | None = None
    ) -> IntentSnapshot:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(DownloadIntentRow)
                .with_for_update()
                .where(
                    DownloadIntentRow.owner_hash == owner_hash,
                    DownloadIntentRow.idempotency_key == idempotency_key,
                )
            )
            if row is None:
                raise RepositoryNotFound("intent not found")
            if now is not None:
                _request_expiry(session, row, now)
            return _snapshot(row)

    async def cancel(
        self, intent_id: UUID, owner_hash: str, *, now: datetime
    ) -> IntentSnapshot:
        validate_now(now)
        async with self._sessions() as session, session.begin():
            row = await self._owned(session, intent_id, owner_hash, lock=True)
            if row.status == IntentStatus.HANDED_OFF.value:
                job = await session.scalar(
                    select(DownloadJobRow)
                    .where(
                        DownloadJobRow.id == row.job_id,
                        DownloadJobRow.owner_hash == owner_hash,
                    )
                    .with_for_update()
                )
                if job is None:
                    raise RepositoryConflict("intent download is unavailable")
                cancel_job_row(job, now)
                _transition(row, IntentStatus.CANCELLED, now, "cancelled")
            if (
                IntentStatus(row.status) not in TERMINAL_INTENT_STATUSES
                and row.status != IntentStatus.CANCELLING.value
            ):
                _transition(row, IntentStatus.CANCELLING, now, "cancelled")
                session.add(_cancel_requested(row, now))
            return _snapshot(row)

    async def confirm_cancel(
        self, intent_id: UUID, generation: int, *, now: datetime
    ) -> IntentSnapshot:
        """The caller must have received the Runner cleanup acknowledgement."""
        validate_now(now)
        async with self._sessions() as session, session.begin():
            row = await session.get(DownloadIntentRow, intent_id, with_for_update=True)
            if row is None:
                raise RepositoryNotFound("intent does not exist")
            if (
                row.generation == generation
                and row.status == IntentStatus.CANCELLING.value
            ):
                target = (
                    IntentStatus.EXPIRED
                    if row.reason_code == "transient"
                    else IntentStatus.CANCELLED
                )
                _transition(row, target, now, row.reason_code)
            return _snapshot(row)

    async def history(
        self,
        owner_hash: str,
        *,
        before: UUID | None = None,
        limit: int = 20,
        now: datetime | None = None,
    ) -> IntentHistoryPage:
        validate_owner_hash(owner_hash)
        if not 1 <= limit <= 50:
            raise ValueError("invalid history page size")
        async with self._sessions() as session, session.begin():
            if now is not None:
                await request_overdue_cleanup(session, owner_hash, now)
            query = (
                select(DownloadIntentRow, MediaInspectionRow.title)
                .outerjoin(
                    MediaInspectionRow,
                    and_(
                        MediaInspectionRow.id == DownloadIntentRow.inspection_id,
                        MediaInspectionRow.owner_hash == owner_hash,
                    ),
                )
                .where(DownloadIntentRow.owner_hash == owner_hash)
            )
            if before is not None:
                cursor = await self._owned(session, before, owner_hash)
                query = query.where(
                    or_(
                        DownloadIntentRow.created_at < cursor.created_at,
                        and_(
                            DownloadIntentRow.created_at == cursor.created_at,
                            DownloadIntentRow.id < cursor.id,
                        ),
                    )
                )
            rows = (
                await session.execute(
                    query.order_by(
                        DownloadIntentRow.created_at.desc(), DownloadIntentRow.id.desc()
                    ).limit(limit + 1)
                )
            ).all()
            items = tuple(
                IntentHistoryEntry(_snapshot(row), title) for row, title in rows[:limit]
            )
            return IntentHistoryPage(
                items, items[-1].intent.id if len(rows) > limit else None
            )

    async def claim(
        self, intent_id: UUID, generation: int, *, now: datetime, recover: bool = False
    ) -> IntentOperation | None:
        validate_now(now)
        async with self._sessions() as session, session.begin():
            row = await session.get(DownloadIntentRow, intent_id, with_for_update=True)
            if (
                row is None
                or row.generation != generation
                or row.status
                not in (
                    (IntentStatus.QUEUED.value, IntentStatus.RESOLVING.value)
                    if recover
                    else (IntentStatus.QUEUED.value,)
                )
            ):
                return None
            if now >= row.deadline:
                _request_expiry(session, row, now)
                return None
            _transition(row, IntentStatus.RESOLVING, now)
            return IntentOperation(
                _snapshot(row),
                EncryptedUrl(row.url_ciphertext, row.url_nonce, row.url_key_id),
            )

    async def execution_state(self, intent_id: UUID) -> IntentSnapshot:
        async with self._sessions() as session:
            row = await session.get(DownloadIntentRow, intent_id)
            if row is None:
                raise RepositoryNotFound("intent does not exist")
            return _snapshot(row)

    async def refresh(
        self,
        intent_id: UUID,
        owner_hash: str,
        *,
        now: datetime,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> IntentSnapshot:
        validate_now(now)
        validate_owner_hash(owner_hash)
        async with self._sessions() as session, session.begin():
            await lock_admission(session, owner_hash)
            row = await self._owned(session, intent_id, owner_hash, lock=True)
            _request_expiry(session, row, now)
            if IntentStatus(row.status) in {
                *RUNNING_INTENT_STATUSES,
                IntentStatus.QUEUED,
                IntentStatus.HANDED_OFF,
            }:
                return _snapshot(row)
            if row.status not in {
                IntentStatus.READY.value,
                IntentStatus.FAILED.value,
                IntentStatus.EXPIRED.value,
            }:
                raise RepositoryConflict("intent cannot refresh in this state")
            if row.status == IntentStatus.READY.value:
                previous = await session.get(MediaInspectionRow, row.inspection_id)
                if previous is None or previous.owner_hash != owner_hash:
                    raise RepositoryConflict("intent result is unavailable")
                if previous.expires_at > now:
                    return _snapshot(row)
            if not quota.exempt:
                await ensure_active_capacity(
                    session, quota.apply(self._quota_policy), owner_hash
                )
            row.generation += 1
            row.deadline = now + _TIMEOUT
            row.execution_context = None
            row.latest_failure = None
            _transition(row, IntentStatus.QUEUED, now)
            session.add(_requested(row, now))
            return _snapshot(row)

    async def complete(
        self, operation: IntentSnapshot, result: InspectionCreate, *, now: datetime
    ) -> IntentSnapshot:
        """Inspection, formats and ready status commit atomically."""
        validate_now(now)
        async with self._sessions() as session, session.begin():
            row = await self._executing(session, operation)
            if row is None:
                raise RepositoryConflict("intent execution superseded")
            if now >= row.deadline:
                _transition(row, IntentStatus.EXPIRED, now, "transient")
                return _snapshot(row)
            if result.owner_hash != row.owner_hash or result.expires_at <= now:
                raise RepositoryConflict("inspection does not match intent scope")
            if result.idempotency_key != f"intent:{row.id}:{row.generation}":
                raise RepositoryConflict("inspection does not match intent identity")
            if row.inspection_id is not None:
                previous = await session.get(MediaInspectionRow, row.inspection_id)
                if previous is None or (
                    previous.owner_hash != row.owner_hash
                    or previous.extractor_key != result.extractor_key
                    or previous.provider_media_id != result.provider_media_id
                    or media_kind_from_metadata(previous.metadata_json)
                    != media_kind_from_metadata(result.metadata)
                ):
                    _transition(row, IntentStatus.FAILED, now, "invalid_input")
                    return _snapshot(row)
            context_document = result.metadata.get("execution_context")
            context = (
                None
                if context_document is None
                else ExecutionContext.from_document(context_document)
            )
            await insert_inspection(session, result)
            row.inspection_id = result.id
            row.execution_context = None if context is None else context.to_document()
            row.latest_failure = None
            _transition(row, IntentStatus.READY, now)
            return _snapshot(row)

    async def fail(
        self,
        operation: IntentSnapshot,
        *,
        now: datetime,
        reason_code: str,
        failure: ProviderFailure | None = None,
    ) -> IntentSnapshot:
        validate_now(now)
        if not reason_code or len(reason_code) > 64:
            raise ValueError("invalid intent reason")
        async with self._sessions() as session, session.begin():
            row = await self._executing(session, operation)
            if row is None:
                raise RepositoryConflict("intent execution superseded")
            fact = failure or ProviderFailure.for_code(reason_code)
            row.latest_failure = PROVIDER_FAILURE.dump_python(fact, mode="json")
            _transition(row, IntentStatus.FAILED, now, reason_code)
            return _snapshot(row)

    @staticmethod
    async def _owned(
        session: AsyncSession, intent_id: UUID, owner_hash: str, *, lock: bool = False
    ) -> DownloadIntentRow:
        statement = select(DownloadIntentRow).where(
            DownloadIntentRow.id == intent_id,
            DownloadIntentRow.owner_hash == owner_hash,
        )
        row = await session.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            raise RepositoryNotFound("intent does not exist")
        return row

    @staticmethod
    async def _executing(
        session: AsyncSession, operation: IntentSnapshot
    ) -> DownloadIntentRow | None:
        row: DownloadIntentRow | None = await session.scalar(
            select(DownloadIntentRow)
            .where(
                DownloadIntentRow.id == operation.id,
                DownloadIntentRow.status.in_(_RUNNING),
                DownloadIntentRow.generation == operation.generation,
                DownloadIntentRow.version == operation.version,
            )
            .with_for_update()
        )
        return row


def _transition(
    row: DownloadIntentRow,
    status: IntentStatus,
    now: datetime,
    reason: str | None = None,
) -> None:
    row.status = status.value
    row.version += 1
    row.reason_code = reason
    row.updated_at = now


def _requested(row: DownloadIntentRow, now: datetime) -> OutboxEventRow:
    return OutboxEventRow(
        id=uuid4(),
        aggregate_type="download_intent",
        aggregate_id=row.id,
        aggregate_version=row.version,
        event_type="download.intent.requested",
        payload={"intent_id": str(row.id), "generation": row.generation},
        available_at=now,
        created_at=now,
    )


def _snapshot(row: DownloadIntentRow) -> IntentSnapshot:
    return IntentSnapshot(
        id=row.id,
        owner_hash=row.owner_hash,
        status=IntentStatus(row.status),
        version=row.version,
        deadline=row.deadline,
        generation=row.generation,
        inspection_id=row.inspection_id,
        job_id=row.job_id,
        reason_code=row.reason_code,
        created_at=row.created_at,
        updated_at=row.updated_at,
        execution_context=None
        if row.execution_context is None
        else ExecutionContext.from_document(row.execution_context),
        latest_failure=None
        if row.latest_failure is None
        else PROVIDER_FAILURE.validate_python(row.latest_failure),
    )


def _expire_if_due(row: DownloadIntentRow, now: datetime) -> bool:
    validate_now(now)
    if row.status in _ACTIVE and row.deadline <= now:
        _transition(row, IntentStatus.CANCELLING, now, "transient")
        return True
    return False


def _cancel_requested(row: DownloadIntentRow, now: datetime) -> OutboxEventRow:
    event = _requested(row, now)
    event.event_type = "download.intent.cancelled"
    return event


def _request_expiry(
    session: AsyncSession, row: DownloadIntentRow, now: datetime
) -> None:
    if _expire_if_due(row, now):
        session.add(_cancel_requested(row, now))


async def request_overdue_cleanup(
    session: AsyncSession, owner_hash: str, now: datetime
) -> None:
    rows = await session.scalars(
        select(DownloadIntentRow)
        .where(
            DownloadIntentRow.owner_hash == owner_hash,
            DownloadIntentRow.status.in_(_ACTIVE),
            DownloadIntentRow.deadline <= now,
        )
        .with_for_update()
    )
    for row in rows:
        _request_expiry(session, row, now)
