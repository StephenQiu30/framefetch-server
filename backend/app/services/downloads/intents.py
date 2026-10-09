"""Persist a validated public parsing request before any upstream operation."""

from collections.abc import Callable
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
from app.services.quotas import DEFAULT_USER_QUOTA, UserQuota
from app.services.source_discoveries.ports import (
    ArticleDiscoveryAdapter,
    ArticleDiscoveryFailure,
    SourceDiscoveryRepository,
)
from app.services.source_discovery import (
    DiscoveryDecisionHint,
    DiscoveryItemKind,
    DiscoveryItemStatus,
)


class IntentPersistence(Protocol):
    async def accept(
        self,
        command: IntentCreate,
        *,
        now: datetime,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> IntentSnapshot: ...
    async def get(
        self, intent_id: UUID, owner_hash: str, *, now: datetime | None = None
    ) -> IntentSnapshot: ...
    async def get_by_key(
        self, idempotency_key: str, owner_hash: str, *, now: datetime | None = None
    ) -> IntentSnapshot: ...
    async def history(
        self,
        owner_hash: str,
        *,
        before: UUID | None,
        limit: int,
        now: datetime | None = None,
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
        discoveries: SourceDiscoveryRepository | None = None,
        article_adapter: ArticleDiscoveryAdapter | None = None,
    ) -> None:
        self._repository = repository
        self._validator = validator
        self._cipher = cipher
        self._fingerprinter = fingerprinter
        self._now = now
        self._new_id = new_id
        self._discoveries = discoveries
        self._article_adapter = article_adapter

    async def create_discovered(
        self,
        discovery_id: UUID,
        item_ref: UUID,
        owner_hash: str,
        idempotency_key: str,
        *,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> IntentSnapshot:
        validate_owner_hash(owner_hash)
        validate_idempotency_key(idempotency_key)
        if self._discoveries is None:
            raise ApplicationError(ApplicationErrorCode.RUNTIME_UNAVAILABLE)
        selected = await self._discoveries.select_item(
            discovery_id, item_ref, owner_hash, self._now()
        )
        if selected is None:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND)
        if (
            selected.item.status is not DiscoveryItemStatus.READY
            or selected.item.decision_hint is not DiscoveryDecisionHint.CANDIDATE
        ):
            raise ApplicationError(ApplicationErrorCode.CONTENT_UNAVAILABLE)
        article = self._cipher.decrypt(selected.discovery.encrypted_url)
        if selected.item.kind is DiscoveryItemKind.OFFICIAL_ACCOUNT_NATIVE:
            url = f"{article}#video={selected.item.identity_evidence_hash}"
        else:
            if self._article_adapter is None:
                raise ApplicationError(ApplicationErrorCode.RUNTIME_UNAVAILABLE)
            try:
                current = await self._article_adapter.discover(article)
            except ArticleDiscoveryFailure as exc:
                raise ApplicationError(
                    ApplicationErrorCode.ARTICLE_DISCOVERY_FAILED
                ) from exc
            matches = [
                item
                for item in current.items
                if item.identity_evidence_hash == selected.item.identity_evidence_hash
                and item.kind is selected.item.kind
                and item.source_url is not None
            ]
            if len(matches) != 1:
                raise ApplicationError(ApplicationErrorCode.CONTENT_UNAVAILABLE)
            target = matches[0].source_url
            assert target is not None
            url = target
        return await self.create(url, owner_hash, idempotency_key, quota=quota)

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
        command = IntentCreate(
            id=self._new_id(),
            owner_hash=owner_hash,
            idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprinter.fingerprint("download_intent", url),
            url=self._cipher.encrypt(url),
        )
        try:
            return await self._repository.accept(command, now=self._now(), quota=quota)
        except PersistenceIdempotencyConflict as exc:
            raise ApplicationError(ApplicationErrorCode.IDEMPOTENCY_CONFLICT) from exc

    async def get(self, intent_id: UUID, owner_hash: str) -> IntentSnapshot:
        try:
            return await self._repository.get(intent_id, owner_hash, now=self._now())
        except PersistenceNotFound as exc:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND) from exc

    async def get_by_key(self, idempotency_key: str, owner_hash: str) -> IntentSnapshot:
        validate_owner_hash(owner_hash)
        validate_idempotency_key(idempotency_key)
        try:
            return await self._repository.get_by_key(
                idempotency_key, owner_hash, now=self._now()
            )
        except PersistenceNotFound as exc:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND) from exc

    async def cancel(self, intent_id: UUID, owner_hash: str) -> IntentSnapshot:
        try:
            return await self._repository.cancel(intent_id, owner_hash, now=self._now())
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
                owner_hash, before=before, limit=limit, now=self._now()
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
