from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.services.documents.rules.screenplay import ScreenplayScene
from app.services.documents.rules.summary import DocumentParseSummary
from app.services.import_execution.document_service import DocumentImportExecution
from app.services.import_execution.errors import ImportVerificationRejected
from app.services.import_execution.models import (
    ImportExecutionSettings,
    ImportVerificationClaim,
    ImportWorkspace,
    VerifiedDocumentImport,
)
from app.services.imports.models import ImportDisposition
from app.services.imports.rules.enums import (
    ContentKind,
    ImportErrorCode,
    ImportSourceFormat,
)

NOW = datetime(2026, 8, 14, 19, 0, tzinfo=UTC)
DOCUMENT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def claim() -> ImportVerificationClaim:
    return ImportVerificationClaim(
        resource_id=DOCUMENT_ID,
        content_kind=ContentKind.SCREENPLAY,
        source_format=ImportSourceFormat.FOUNTAIN,
        attempt=2,
        version=4,
        object_key=f"quarantine/screenplay/{DOCUMENT_ID}/2/source",
        declared_size_bytes=128,
        declared_sha256="a" * 64,
    )


class FakeRepository:
    def __init__(self) -> None:
        self.claimed = claim()
        self.heartbeats: list[tuple[str, int]] = []
        self.completed: list[VerifiedDocumentImport] = []
        self.failed: list[ImportErrorCode] = []

    async def claim_verification(self, *args, **kwargs):
        return self.claimed

    async def heartbeat_verification(self, *args, **kwargs):
        self.heartbeats.append((kwargs["stage"], kwargs["progress"]))
        return True

    async def complete_verification(self, claim, artifact, **kwargs):
        self.completed.append(artifact)

    async def fail_verification(self, claim, error_code, **kwargs):
        self.failed.append(error_code)

    async def recover_expired_verifications(self, now, *, limit):
        return ()

    async def expected_artifact_object_keys(self):
        return frozenset()


class FakeStorage:
    def __init__(self) -> None:
        self.promotions: list[tuple[str, str]] = []
        self.uploads: list[tuple[Path, str]] = []
        self.deletes: list[str] = []

    async def download(self, object_key: str, target: Path) -> None:
        target.write_bytes(b"source")

    async def promote(self, source_key: str, destination_key: str, **kwargs):
        self.promotions.append((source_key, destination_key))
        return object()

    async def upload_verified(self, source: Path, destination_key: str, **kwargs):
        self.uploads.append((source, destination_key))
        return object()

    async def delete(self, object_key: str) -> None:
        self.deletes.append(object_key)

    async def list(self, prefix: str):
        return ()


class FakeWorkspace:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.cleaned = False

    async def create(self, task_id: str) -> ImportWorkspace:
        path = self.root / f"{task_id}-random"
        path.mkdir()
        return ImportWorkspace(path, path / "source")

    async def cleanup(self, task_id: str, workspace: Path | None) -> None:
        self.cleaned = True

    async def cleanup_orphans(self, now, *, older_than, limit):
        return 0


class FakeVerifier:
    def __init__(self) -> None:
        self.error: Exception | None = None

    async def __call__(self, path: Path, requested: ImportVerificationClaim):
        if self.error is not None:
            raise self.error
        normalized = path.parent / "screenplay.md"
        normalized.write_text("INT. ROOM - DAY\nText\n", encoding="utf-8")
        return VerifiedDocumentImport(
            original_sha256="a" * 64,
            original_size_bytes=128,
            original_content_type=ImportSourceFormat.FOUNTAIN.content_type,
            normalized_path=normalized,
            normalized_sha256="b" * 64,
            normalized_size_bytes=21,
            detected_language="en-US",
            character_count=21,
            scenes=(ScreenplayScene("scene-0001-123456789abc", 0, 21),),
            quality_warnings=(),
            parse_summary=DocumentParseSummary(None, 2, 1, 0, 0, 0),
        )


def execution(tmp_path: Path):
    repository = FakeRepository()
    storage = FakeStorage()
    workspace = FakeWorkspace(tmp_path)
    verifier = FakeVerifier()
    service = DocumentImportExecution(
        repository=repository,
        storage=storage,
        workspace=workspace,
        verifier=verifier,
        clock=lambda: NOW,
        settings=ImportExecutionSettings(
            worker_id="worker-a",
            bucket="video-artifacts",
            workspace_root=tmp_path,
            lease_for=timedelta(seconds=30),
            heartbeat_interval=5,
        ),
    )
    return service, repository, storage, workspace, verifier


async def test_document_success_promotes_original_and_normalized_before_commit(
    tmp_path: Path,
) -> None:
    service, repository, storage, workspace, _ = execution(tmp_path)

    result = await service.execute(DOCUMENT_ID, ContentKind.SCREENPLAY, 2, 4)

    prefix = f"documents/{DOCUMENT_ID}/2"
    assert result is ImportDisposition.ACK
    assert repository.heartbeats == [
        ("verifying", 60),
        ("verifying", 75),
        ("uploading", 90),
        ("uploading", 95),
    ]
    assert storage.promotions == [(claim().object_key, f"{prefix}/original")]
    assert storage.uploads[0][1] == f"{prefix}/document.md"
    assert len(repository.completed) == 1
    assert storage.deletes == [claim().object_key]
    assert workspace.cleaned is True


async def test_document_rejection_is_terminal_and_cleans_quarantine(
    tmp_path: Path,
) -> None:
    service, repository, storage, workspace, verifier = execution(tmp_path)
    verifier.error = ImportVerificationRejected(
        ImportErrorCode.DOCUMENT_TEXT_UNAVAILABLE, "invalid text"
    )

    result = await service.execute(DOCUMENT_ID, ContentKind.SCREENPLAY, 2, 4)

    assert result is ImportDisposition.ACK
    assert repository.failed == [ImportErrorCode.DOCUMENT_TEXT_UNAVAILABLE]
    assert repository.completed == []
    assert storage.promotions == [] and storage.uploads == []
    assert storage.deletes == [claim().object_key]
    assert workspace.cleaned is True
