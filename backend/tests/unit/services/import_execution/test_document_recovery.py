from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.services.import_execution.document_recovery import (
    DocumentImportRecoverySweeper,
)

NOW = datetime(2026, 8, 14, 20, 0, tzinfo=UTC)
DOCUMENT_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")


@dataclass(frozen=True)
class Stored:
    object_key: str
    last_modified: datetime


class Repository:
    async def recover_expired_verifications(self, now, *, limit):
        return (DOCUMENT_ID,)

    async def expected_artifact_object_keys(self):
        return frozenset(
            {
                f"documents/{DOCUMENT_ID}/1/original",
                f"documents/{DOCUMENT_ID}/1/document.md",
            }
        )


class Storage:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def list(self, prefix: str):
        assert prefix == "documents/"
        other = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
        return (
            Stored(f"documents/{DOCUMENT_ID}/1/original", NOW - timedelta(hours=2)),
            Stored(f"documents/{DOCUMENT_ID}/1/document.md", NOW - timedelta(hours=2)),
            Stored(f"documents/{other}/1/screenplay.md", NOW - timedelta(hours=2)),
            Stored(f"documents/{other}/1/document.md", NOW - timedelta(hours=2)),
            Stored(f"documents/{other}/1/original", NOW),
            Stored("documents/unmanaged/content", NOW - timedelta(days=1)),
        )

    async def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)


async def test_document_recovery_only_deletes_safe_old_unreferenced_artifacts() -> None:
    storage = Storage()
    sweeper = DocumentImportRecoverySweeper(
        Repository(),  # type: ignore[arg-type]
        storage,  # type: ignore[arg-type]
        lambda: NOW,
        interval=5,
        batch_size=10,
        orphan_grace=timedelta(hours=1),
        delete_timeout=5,
    )

    recovered = await sweeper.tick()

    other = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    assert recovered == (DOCUMENT_ID,)
    assert storage.deleted == [
        f"documents/{other}/1/screenplay.md",
        f"documents/{other}/1/document.md",
    ]
