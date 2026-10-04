from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta
from uuid import UUID

from app.services.import_execution.document_ports import (
    DocumentImportExecutionRepository,
)
from app.services.import_execution.ports import Clock, ImportExecutionStorage

_log = logging.getLogger(__name__)

_DOCUMENT_ARTIFACT_KEY = re.compile(
    r"documents/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}/[1-9][0-9]*/"
    r"(?:original|document\.md|screenplay\.md)"
)


class DocumentImportRecoverySweeper:
    def __init__(
        self,
        repository: DocumentImportExecutionRepository,
        storage: ImportExecutionStorage,
        clock: Clock,
        *,
        interval: float,
        batch_size: int,
        orphan_grace: timedelta,
        delete_timeout: float,
    ) -> None:
        if (
            interval <= 0
            or not 1 <= batch_size <= 200
            or orphan_grace.total_seconds() <= 0
            or delete_timeout <= 0
        ):
            raise ValueError("invalid document recovery settings")
        self._repository = repository
        self._storage = storage
        self._clock = clock
        self._interval = interval
        self._batch_size = batch_size
        self._orphan_grace = orphan_grace
        self._delete_timeout = delete_timeout

    async def tick(self) -> tuple[UUID, ...]:
        now = self._clock()
        recovered = await self._repository.recover_expired_verifications(
            now, limit=self._batch_size
        )
        expected = await self._repository.expected_artifact_object_keys()
        cutoff = now - self._orphan_grace
        deleted = 0
        for item in await self._storage.list("documents/"):
            if deleted >= self._batch_size:
                break
            if (
                item.object_key in expected
                or _DOCUMENT_ARTIFACT_KEY.fullmatch(item.object_key) is None
                or item.last_modified > cutoff
            ):
                continue
            await asyncio.wait_for(
                self._storage.delete(item.object_key), timeout=self._delete_timeout
            )
            deleted += 1
        return recovered

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:
                _log.exception("document import recovery sweep failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._interval)
            except TimeoutError:
                pass
