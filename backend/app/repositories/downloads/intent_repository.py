"""Short PostgreSQL transactions own intent acceptance, fenced result commits.

Network work happens between beginning and completing an operation,
never under a row lock.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.download import DownloadJobRow
from app.models.download_intent import DownloadIntentRow, ResolutionAttemptRow
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
from app.schemas.resolution import PROVIDER_FAILURE, RESOLUTION_PLAN
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
from app.services.downloads.resolution import (
    ResolutionAction,
    ResolutionAttemptStatus,
    ResolutionExecution,
    ResolutionPlan,
    ResolutionPreparation,
    decide_resolution,
    failure_signature,
    preparation_failure_is_terminal,
    unchanged_failure_is_terminal,
)
from app.services.downloads.resolution import (
    operation_id as inspection_operation_id,
)
from app.services.downloads.validation import (
    media_kind_from_metadata,
    validate_idempotency_key,
    validate_now,
    validate_owner_hash,
)
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_failures import (
    FailureEvidenceKind,
    FailurePhase,
    ProviderFailure,
)
from app.services.provider_types import ProviderAccessContextRef
from app.services.quotas import DEFAULT_USER_QUOTA, QuotaPolicy, UserQuota

_RUNNING = tuple(status.value for status in RUNNING_INTENT_STATUSES)
_BUDGET = timedelta(seconds=180)


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
                    access_policy=command.access_policy.value,
                    deadline=now + _BUDGET,
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

    async def get(self, intent_id: UUID, owner_hash: str) -> IntentSnapshot:
        async with self._sessions() as session:
            row = await self._owned(session, intent_id, owner_hash)
            return _snapshot(row)

    async def get_by_key(self, idempotency_key: str, owner_hash: str) -> IntentSnapshot:
        async with self._sessions() as session:
            row = await session.scalar(
                select(DownloadIntentRow).where(
                    DownloadIntentRow.owner_hash == owner_hash,
                    DownloadIntentRow.idempotency_key == idempotency_key,
                )
            )
            if row is None:
                raise RepositoryNotFound("intent not found")
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
            if IntentStatus(row.status) not in TERMINAL_INTENT_STATUSES:
                await _finish_attempt(
                    session, row, now, ResolutionAttemptStatus.OUTCOME_UNKNOWN
                )
                _transition(row, IntentStatus.CANCELLED, now, "cancelled")
                row.fence += 1
                event = _requested(row, now)
                event.event_type = "download.intent.cancelled"
                session.add(event)
            return _snapshot(row)

    async def history(
        self, owner_hash: str, *, before: UUID | None = None, limit: int = 20
    ) -> IntentHistoryPage:
        validate_owner_hash(owner_hash)
        if not 1 <= limit <= 50:
            raise ValueError("invalid history page size")
        async with self._sessions() as session:
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

    async def claim_preparation(
        self, intent_id: UUID, generation: int, operation_id: str, *, now: datetime
    ) -> IntentOperation | None:
        """Reserve preparation without spending a platform call or stealing work."""
        validate_now(now)
        if not operation_id or len(operation_id) > 128 or generation < 0:
            raise ValueError("invalid intent operation")
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(DownloadIntentRow)
                .where(DownloadIntentRow.id == intent_id)
                .with_for_update()
            )
            if (
                row is None
                or row.generation != generation
                or row.status
                not in {
                    IntentStatus.QUEUED.value,
                    IntentStatus.RETRY_WAIT.value,
                    *_RUNNING,
                }
            ):
                return None
            if row.status in _RUNNING:
                return IntentOperation(
                    _snapshot(row),
                    EncryptedUrl(row.url_ciphertext, row.url_nonce, row.url_key_id),
                    newly_claimed=False,
                )
            if row.operation_id != operation_id:
                if _exhausted(row, now):
                    _expire(row, now)
                    return None
                if row.retry_at is not None and row.retry_at > now:
                    raise RepositoryConflict("retry timer has not elapsed")
                _transition(row, IntentStatus.PREPARING, now)
                row.fence += 1
                row.operation_id = operation_id
            elif _remaining(row, now) == 0:
                _expire(row, now)
                return None
            return IntentOperation(
                _snapshot(row),
                EncryptedUrl(row.url_ciphertext, row.url_nonce, row.url_key_id),
            )

    async def bind_plan(
        self, operation: IntentSnapshot, plan: ResolutionPlan, *, now: datetime
    ) -> IntentSnapshot:
        async with self._sessions() as session, session.begin():
            row = await self._executing(session, operation)
            if row is None or row.status != IntentStatus.PREPARING.value:
                raise RepositoryConflict("intent preparation superseded")
            if (
                plan.generation != row.generation
                or plan.capability.access_policy.value != row.access_policy
            ):
                raise RepositoryConflict("resolution plan scope mismatch")
            document = RESOLUTION_PLAN.dump_python(plan, mode="json")
            if row.resolution_plan is not None:
                if row.resolution_plan != document:
                    raise RepositoryConflict("resolution plan is immutable")
            else:
                row.resolution_plan = document
                row.next_strategy_id = plan.first_strategy.strategy_id
                row.version += 1
                row.updated_at = now
            return _snapshot(row)

    async def begin_attempt(
        self,
        operation: IntentSnapshot,
        preparation: ResolutionPreparation,
        *,
        now: datetime,
    ) -> IntentOperation | None:
        """Register the one execution identity before submitting platform I/O."""
        validate_now(now)
        async with self._sessions() as session, session.begin():
            row = await self._executing(session, operation)
            if row is None or row.status != IntentStatus.PREPARING.value:
                return None
            snapshot = _snapshot(row)
            plan = snapshot.resolution_plan
            if plan is None or snapshot.next_strategy_id is None:
                raise RepositoryConflict("resolution plan is missing")
            if _exhausted(row, now):
                _expire(row, now)
                return None
            strategy = plan.strategy(snapshot.next_strategy_id)
            context = preparation.context
            if (
                context.provider_key != plan.capability.provider_key
                or context.profile_version != plan.capability.profile_version
                or context.strategy_id != strategy.strategy_id
                or context.adapter_revision != strategy.adapter_revision
                or context.access_mode != strategy.access_mode
            ):
                raise RepositoryConflict("resolution preparation context mismatch")
            previous = await session.scalar(
                select(ResolutionAttemptRow)
                .where(
                    ResolutionAttemptRow.intent_id == row.id,
                    ResolutionAttemptRow.generation == row.generation,
                    ResolutionAttemptRow.strategy_id == strategy.strategy_id,
                    ResolutionAttemptRow.context_key == context.generation_id,
                    ResolutionAttemptRow.status == ResolutionAttemptStatus.FAILED.value,
                )
                .order_by(ResolutionAttemptRow.attempt_no.desc())
                .limit(1)
            )
            if previous is not None and previous.failure is not None:
                failure = PROVIDER_FAILURE.validate_python(previous.failure)
                if unchanged_failure_is_terminal(failure):
                    row.latest_failure = previous.failure
                    # Automatic preparation has read the same approved source.
                    # Unchanged evidence cannot justify another platform call.
                    _transition(
                        row, IntentStatus.FAILED, now, row.reason_code or failure.code
                    )
                    return None
            row.attempt += 1
            row.fence += 1
            identifier = inspection_operation_id(row.id, row.generation, row.attempt)
            execution = ResolutionExecution(
                strategy.strategy_id,
                plan.revision,
                identifier,
                context,
                preparation.runner_instance_id,
                now
                + timedelta(
                    milliseconds=min(row.remaining_budget_ms, strategy.step_timeout_ms)
                ),
            )
            _transition(row, IntentStatus.RESOLVING, now)
            row.operation_id = identifier
            session.add(
                ResolutionAttemptRow(
                    operation_id=identifier,
                    intent_id=row.id,
                    generation=row.generation,
                    attempt_no=row.attempt,
                    fence=row.fence,
                    strategy_id=strategy.strategy_id,
                    plan_revision=plan.revision,
                    plan_snapshot=row.resolution_plan if row.attempt == 1 else None,
                    context_key=context.generation_id,
                    access_context=context.to_document(),
                    runner_instance_id=execution.runner_instance_id,
                    deadline_at=execution.deadline_at,
                    started_at=now,
                    status=ResolutionAttemptStatus.STARTED.value,
                )
            )
            return IntentOperation(
                _snapshot(row),
                EncryptedUrl(row.url_ciphertext, row.url_nonce, row.url_key_id),
                execution=execution,
            )

    async def running_operation(
        self, intent_id: UUID, generation: int
    ) -> IntentOperation | None:
        async with self._sessions() as session:
            row = await session.get(DownloadIntentRow, intent_id)
            if (
                row is None
                or row.generation != generation
                or row.status != IntentStatus.RESOLVING.value
            ):
                return None
            attempt = await session.get(ResolutionAttemptRow, row.operation_id)
            if attempt is None:
                raise RepositoryConflict("resolution execution receipt missing")
            return IntentOperation(
                _snapshot(row),
                EncryptedUrl(row.url_ciphertext, row.url_nonce, row.url_key_id),
                newly_claimed=False,
                execution=ResolutionExecution(
                    attempt.strategy_id,
                    attempt.plan_revision,
                    attempt.operation_id,
                    ProviderAccessContextRef.from_document(attempt.access_context),
                    attempt.runner_instance_id,
                    attempt.deadline_at,
                ),
            )

    async def execution_state(self, intent_id: UUID) -> IntentSnapshot:
        async with self._sessions() as session:
            row = await session.get(DownloadIntentRow, intent_id)
            if row is None:
                raise RepositoryNotFound("intent does not exist")
            return _snapshot(row)

    async def fail_generation(
        self, intent_id: UUID, generation: int, *, now: datetime
    ) -> IntentSnapshot:
        """Reconcile an exhausted Temporal execution without rerunning its work."""
        async with self._sessions() as session, session.begin():
            row = await session.get(DownloadIntentRow, intent_id, with_for_update=True)
            if row is None:
                raise RepositoryNotFound("intent does not exist")
            if row.generation == generation and row.status in {
                IntentStatus.QUEUED.value,
                IntentStatus.RETRY_WAIT.value,
                *_RUNNING,
            }:
                failure = ProviderFailure.for_code(
                    "outcome_unknown",
                    phase=FailurePhase.FETCH_METADATA,
                    evidence_kind=FailureEvidenceKind.RUNTIME,
                )
                await _finish_attempt(
                    session,
                    row,
                    now,
                    ResolutionAttemptStatus.OUTCOME_UNKNOWN,
                    failure=failure,
                )
                row.latest_failure = PROVIDER_FAILURE.dump_python(failure, mode="json")
                row.fence += 1
                _transition(row, IntentStatus.FAILED, now, "inspection_failed")
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
            if IntentStatus(row.status) in {
                *RUNNING_INTENT_STATUSES,
                IntentStatus.QUEUED,
                IntentStatus.RETRY_WAIT,
                IntentStatus.HANDED_OFF,
            }:
                return _snapshot(row)
            if row.status not in {
                IntentStatus.READY.value,
                IntentStatus.FAILED.value,
                IntentStatus.EXPIRED.value,
            }:
                raise RepositoryConflict("intent cannot refresh in this state")
            unresolved = await session.scalar(
                select(ResolutionAttemptRow.operation_id)
                .where(
                    ResolutionAttemptRow.intent_id == row.id,
                    ResolutionAttemptRow.status.in_(
                        (
                            ResolutionAttemptStatus.STARTED.value,
                            ResolutionAttemptStatus.OUTCOME_UNKNOWN.value,
                        )
                    ),
                )
                .limit(1)
            )
            if unresolved is not None:
                raise RepositoryConflict(
                    "previous execution termination is unconfirmed"
                )
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
            # Only an explicit refresh creates a new execution generation.
            row.attempt = 0
            row.remaining_budget_ms = 180_000
            row.deadline = now + _BUDGET
            row.resolution_plan = None
            row.next_strategy_id = None
            row.selected_operation_id = None
            row.latest_failure = None
            row.fence += 1
            _transition(row, IntentStatus.QUEUED, now)
            session.add(_requested(row, now))
            return _snapshot(row)

    async def complete(
        self, operation: IntentSnapshot, result: InspectionCreate, *, now: datetime
    ) -> IntentSnapshot:
        """Inspection, formats and ready status commit atomically behind fencing."""
        validate_now(now)
        async with self._sessions() as session, session.begin():
            row = await self._executing(session, operation)
            if row is None:
                existing = await session.get(DownloadIntentRow, operation.id)
                if (
                    existing is not None
                    and existing.selected_operation_id == operation.operation_id
                    and existing.inspection_id == result.id
                ):
                    return _snapshot(existing)
                raise RepositoryConflict("intent execution superseded")
            if _remaining(row, now) == 0:
                await _finish_attempt(
                    session,
                    row,
                    now,
                    ResolutionAttemptStatus.FAILED,
                    failure=ProviderFailure.for_code("inspection_timeout"),
                )
                _expire(row, now)
                return _snapshot(row)
            if (
                result.owner_hash != row.owner_hash
                or result.metadata.get("access_policy_id") != row.access_policy
                or result.expires_at <= now
            ):
                raise RepositoryConflict("inspection does not match intent scope")
            # This namespace is reserved for durable intent results; clients never
            # select its inspection key or reuse another intent's result.
            if result.idempotency_key != f"intent:{row.id}:{row.fence}":
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
                    await _finish_attempt(
                        session,
                        row,
                        now,
                        ResolutionAttemptStatus.FAILED,
                        failure=ProviderFailure.for_code("provider_unsupported"),
                    )
                    _transition(row, IntentStatus.FAILED, now, "unsupported_source")
                    return _snapshot(row)
            await insert_inspection(session, result)
            row.inspection_id = result.id
            row.selected_operation_id = (
                operation.operation_id
                if row.status == IntentStatus.RESOLVING.value
                else None
            )
            row.latest_failure = None
            await _finish_attempt(
                session,
                row,
                now,
                ResolutionAttemptStatus.SUCCEEDED,
                inspection_id=result.id,
            )
            _transition(row, IntentStatus.READY, now)
            return _snapshot(row)

    async def fail(
        self,
        operation: IntentSnapshot,
        *,
        now: datetime,
        reason_code: str,
        retry_at: datetime | None = None,
        failure: ProviderFailure | None = None,
    ) -> IntentSnapshot:
        validate_now(now)
        if not reason_code or len(reason_code) > 64:
            raise ValueError("invalid intent reason")
        if retry_at is not None:
            validate_now(retry_at)
            if retry_at <= now:
                raise ValueError("retry must be scheduled in the future")
        async with self._sessions() as session, session.begin():
            row = await self._executing(session, operation)
            if row is None:
                raise RepositoryConflict("intent execution superseded")
            fact = failure or ProviderFailure.for_code(
                reason_code,
                phase=(
                    FailurePhase.PREPARE_CONTEXT
                    if row.status == IntentStatus.PREPARING.value
                    else FailurePhase.FETCH_METADATA
                ),
                evidence_kind=FailureEvidenceKind.LOCAL_VALIDATION,
            )
            row.latest_failure = PROVIDER_FAILURE.dump_python(fact, mode="json")
            await _finish_attempt(
                session, row, now, ResolutionAttemptStatus.FAILED, failure=fact
            )
            if _remaining(row, now) == 0:
                _expire(row, now)
                return _snapshot(row)
            if preparation_failure_is_terminal(fact):
                _transition(row, IntentStatus.FAILED, now, reason_code)
                return _snapshot(row)
            plan = _snapshot(row).resolution_plan
            if (
                row.status == IntentStatus.RESOLVING.value
                and plan is not None
                and row.next_strategy_id is not None
            ):
                decision = decide_resolution(
                    plan,
                    row.next_strategy_id,
                    fact,
                    attempt=row.attempt,
                    remaining_budget_ms=_remaining(row, now),
                    now=now,
                )
                row.next_strategy_id = decision.strategy_id
                if decision.action is ResolutionAction.CONTINUE:
                    _transition(row, IntentStatus.QUEUED, now, reason_code)
                elif (
                    decision.action in {ResolutionAction.RETRY, ResolutionAction.WAIT}
                    and decision.retry_at is not None
                    and decision.retry_at < row.deadline
                ):
                    _transition(row, IntentStatus.RETRY_WAIT, now, reason_code)
                    row.retry_at = max(decision.retry_at, retry_at or decision.retry_at)
                    if row.retry_at >= row.deadline:
                        _transition(row, IntentStatus.FAILED, now, reason_code)
                else:
                    _transition(row, IntentStatus.FAILED, now, reason_code)
                return _snapshot(row)
            if row.access_policy in {
                ProviderAccessPolicy.PUBLIC_SESSION.value,
                ProviderAccessPolicy.OPERATOR_PUBLIC.value,
                ProviderAccessPolicy.PERSONAL_ENTITLED.value,
            } and reason_code in {
                "provider_auth_required",
                "provider_session_expired",
                "provider_session_not_ready",
            }:
                _wait_for_context(row, now, reason_code, retry_at=retry_at)
                return _snapshot(row)
            if (
                retry_at is not None
                and row.attempt < row.max_attempts
                and retry_at < row.deadline
            ):
                _transition(row, IntentStatus.RETRY_WAIT, now, reason_code)
                row.retry_at = retry_at
            else:
                _transition(row, IntentStatus.FAILED, now, reason_code)
            return _snapshot(row)

    async def abandon_attempt(
        self, operation: IntentSnapshot, *, now: datetime
    ) -> None:
        """Cancellation reaches this only after Runner cleanup has been awaited."""
        if operation.operation_id is None:
            return
        async with self._sessions() as session, session.begin():
            attempt = await session.get(
                ResolutionAttemptRow, operation.operation_id, with_for_update=True
            )
            if (
                attempt is not None
                and attempt.fence == operation.fence
                and attempt.status
                in {
                    ResolutionAttemptStatus.STARTED.value,
                    ResolutionAttemptStatus.OUTCOME_UNKNOWN.value,
                }
            ):
                attempt.status = ResolutionAttemptStatus.ABANDONED.value
                attempt.finished_at = now
                attempt.duration_ms = min(
                    180_000,
                    max(0, int((now - attempt.started_at).total_seconds() * 1000)),
                )

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
                DownloadIntentRow.operation_id == operation.operation_id,
                DownloadIntentRow.generation == operation.generation,
                DownloadIntentRow.fence == operation.fence,
                DownloadIntentRow.version == operation.version,
            )
            .with_for_update()
        )
        return row


def _remaining(row: DownloadIntentRow, now: datetime) -> int:
    elapsed = (
        max(0, int((now - row.updated_at).total_seconds() * 1000))
        if row.status == IntentStatus.RESOLVING.value
        else 0
    )
    return max(0, row.remaining_budget_ms - elapsed)


def _exhausted(row: DownloadIntentRow, now: datetime) -> bool:
    return (
        _remaining(row, now) == 0
        or row.attempt >= row.max_attempts
        or now >= row.deadline
    )


def _expire(row: DownloadIntentRow, now: datetime) -> None:
    timed_out = _remaining(row, now) == 0 or now >= row.deadline
    _transition(
        row,
        IntentStatus.EXPIRED if timed_out else IntentStatus.FAILED,
        now,
        "inspection_timeout" if timed_out else "inspection_failed",
    )


def _transition(
    row: DownloadIntentRow,
    status: IntentStatus,
    now: datetime,
    reason: str | None = None,
) -> None:
    remaining = _remaining(row, now)
    row.status = status.value
    row.version += 1
    row.operation_id = None
    row.retry_at = None
    row.reason_code = reason
    row.remaining_budget_ms = remaining
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
        access_policy=ProviderAccessPolicy(row.access_policy),
        version=row.version,
        fence=row.fence,
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        remaining_budget_ms=row.remaining_budget_ms,
        deadline=row.deadline,
        generation=row.generation,
        operation_id=row.operation_id,
        retry_at=row.retry_at,
        inspection_id=row.inspection_id,
        job_id=row.job_id,
        reason_code=row.reason_code,
        created_at=row.created_at,
        updated_at=row.updated_at,
        resolution_plan=None
        if row.resolution_plan is None
        else RESOLUTION_PLAN.validate_python(row.resolution_plan),
        next_strategy_id=row.next_strategy_id,
        selected_operation_id=row.selected_operation_id,
        latest_failure=None
        if row.latest_failure is None
        else PROVIDER_FAILURE.validate_python(row.latest_failure),
    )


def _wait_for_context(
    row: DownloadIntentRow, now: datetime, reason: str, *, retry_at: datetime | None
) -> None:
    # Preparation remains bounded by the originally accepted deadline. It does
    # not consume a platform attempt or create a new generation/context key.
    scheduled = max(now + timedelta(seconds=15), retry_at or now)
    if scheduled >= row.deadline:
        _transition(row, IntentStatus.FAILED, now, reason)
    else:
        _transition(row, IntentStatus.RETRY_WAIT, now, reason)
        row.retry_at = scheduled


async def _finish_attempt(
    session: AsyncSession,
    row: DownloadIntentRow,
    now: datetime,
    status: ResolutionAttemptStatus,
    *,
    failure: ProviderFailure | None = None,
    inspection_id: UUID | None = None,
) -> None:
    if row.operation_id is None or row.status != IntentStatus.RESOLVING.value:
        return
    attempt = await session.get(
        ResolutionAttemptRow, row.operation_id, with_for_update=True
    )
    if attempt is None or attempt.status != ResolutionAttemptStatus.STARTED.value:
        return
    attempt.status = status.value
    attempt.finished_at = now
    attempt.duration_ms = min(
        row.remaining_budget_ms,
        max(0, int((now - attempt.started_at).total_seconds() * 1000)),
    )
    attempt.inspection_id = inspection_id
    if failure is not None:
        fact = replace(
            failure,
            strategy_id=failure.strategy_id or attempt.strategy_id,
            context_key=failure.context_key or attempt.context_key,
        )
        attempt.failure = PROVIDER_FAILURE.dump_python(fact, mode="json")
        row.latest_failure = attempt.failure
        attempt.evidence_signature = failure_signature(fact)
