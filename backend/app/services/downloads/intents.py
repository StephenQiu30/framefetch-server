"""Persist a validated public parsing request before any upstream operation."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.services.downloads.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PersistenceConflict,
    PersistenceIdempotencyConflict,
    PersistenceNotFound,
)
from app.services.downloads.intent_models import (
    IntentCreate,
    IntentHistoryPage,
    IntentSnapshot,
)
from app.services.downloads.ports import RequestFingerprinter, UrlCipher, UrlValidator
from app.services.downloads.validation import (
    validate_idempotency_key,
    validate_owner_hash,
)
from app.services.provider_access import ProviderAccessPolicy
from app.services.quotas import DEFAULT_USER_QUOTA, UserQuota


class IntentPersistence(Protocol):
    async def accept(
        self,
        command: IntentCreate,
        *,
        now: datetime,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> IntentSnapshot: ...
    async def get(self, intent_id: UUID, owner_hash: str) -> IntentSnapshot: ...
    async def get_by_key(
        self, idempotency_key: str, owner_hash: str
    ) -> IntentSnapshot: ...
    async def history(
        self, owner_hash: str, *, before: UUID | None, limit: int
    ) -> IntentHistoryPage: ...
    async def refresh(
        self,
        intent_id: UUID,
        owner_hash: str,
        *,
        now: datetime,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> IntentSnapshot: ...
    async def cancel(
        self, intent_id: UUID, owner_hash: str, *, now: datetime
    ) -> IntentSnapshot: ...
    async def resume(
        self, intent_id: UUID, owner_hash: str, authorization_id: UUID, *, now: datetime
    ) -> IntentSnapshot: ...


class IntentService:
    def __init__(
        self,
        repository: IntentPersistence,
        validator: UrlValidator,
        cipher: UrlCipher,
        fingerprinter: RequestFingerprinter,
        *,
        now: Callable[[], datetime],
        new_id: Callable[[], UUID],
        select_policy: Callable[[str], Awaitable[ProviderAccessPolicy]] | None = None,
    ) -> None:
        self._repository = repository
        self._validator = validator
        self._cipher = cipher
        self._fingerprinter = fingerprinter
        self._now = now
        self._new_id = new_id
        self._select_policy = select_policy

    async def create(
        self,
        value: str,
        owner_hash: str,
        idempotency_key: str,
        *,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> IntentSnapshot:
        validate_owner_hash(owner_hash)
        validate_idempotency_key(idempotency_key)
        try:
            url = self._validator.validate(value)
        except ValueError as exc:
            raise ApplicationError(ApplicationErrorCode.INVALID_URL) from exc
        policy = (
            ProviderAccessPolicy.PUBLIC
            if self._select_policy is None
            else await self._select_policy(url)
        )
        command = IntentCreate(
            id=self._new_id(),
            owner_hash=owner_hash,
            idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprinter.fingerprint("download_intent", url),
            url=self._cipher.encrypt(url),
            access_policy=policy,
        )
        try:
            return await self._repository.accept(command, now=self._now(), quota=quota)
        except PersistenceIdempotencyConflict as exc:
            raise ApplicationError(ApplicationErrorCode.IDEMPOTENCY_CONFLICT) from exc

    async def get(self, intent_id: UUID, owner_hash: str) -> IntentSnapshot:
        try:
            return await self._repository.get(intent_id, owner_hash)
        except PersistenceNotFound as exc:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND) from exc

    async def get_by_key(self, idempotency_key: str, owner_hash: str) -> IntentSnapshot:
        validate_owner_hash(owner_hash)
        validate_idempotency_key(idempotency_key)
        try:
            return await self._repository.get_by_key(idempotency_key, owner_hash)
        except PersistenceNotFound as exc:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND) from exc

    async def cancel(self, intent_id: UUID, owner_hash: str) -> IntentSnapshot:
        try:
            return await self._repository.cancel(intent_id, owner_hash, now=self._now())
        except PersistenceNotFound as exc:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND) from exc
        except PersistenceConflict as exc:
            raise ApplicationError(ApplicationErrorCode.INVALID_STATE) from exc

    async def resume(
        self, intent_id: UUID, owner_hash: str, authorization_id: UUID
    ) -> IntentSnapshot:
        try:
            return await self._repository.resume(
                intent_id, owner_hash, authorization_id, now=self._now()
            )
        except PersistenceNotFound as exc:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND) from exc
        except PersistenceConflict as exc:
            raise ApplicationError(ApplicationErrorCode.INVALID_STATE) from exc

    async def history(
        self, owner_hash: str, *, before: UUID | None = None, limit: int = 20
    ) -> IntentHistoryPage:
        validate_owner_hash(owner_hash)
        if not 1 <= limit <= 50:
            raise ValueError("invalid history page size")
        try:
            return await self._repository.history(
                owner_hash, before=before, limit=limit
            )
        except PersistenceNotFound as exc:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND) from exc

    async def refresh(
        self, intent_id: UUID, owner_hash: str, *, quota: UserQuota = DEFAULT_USER_QUOTA
    ) -> IntentSnapshot:
        validate_owner_hash(owner_hash)
        try:
            return await self._repository.refresh(
                intent_id, owner_hash, now=self._now(), quota=quota
            )
        except PersistenceNotFound as exc:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND) from exc
        except PersistenceConflict as exc:
            raise ApplicationError(ApplicationErrorCode.INVALID_STATE) from exc
