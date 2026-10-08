from __future__ import annotations

from pathlib import Path

import pytest
from app.integrations.workspace_content import WorkspaceContentStore
from app.services.workspace_documents.errors import (
    WorkspaceDocumentError,
    WorkspaceDocumentErrorCode,
)
from app.services.workspace_documents.rules import MAX_DOCUMENT_BYTES, content_digest


@pytest.fixture
def store(tmp_path: Path) -> WorkspaceContentStore:
    (tmp_path / "design").mkdir()
    (tmp_path / "design/01-边界.md").write_text(
        "# 产品边界\n\n正文\n", encoding="utf-8"
    )
    (tmp_path / "index.mdx").write_text("# 首页\n", encoding="utf-8")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian/notes.md").write_text("# 私有\n", encoding="utf-8")
    return WorkspaceContentStore(tmp_path)


def _code(
    error: pytest.ExceptionInfo[WorkspaceDocumentError],
) -> WorkspaceDocumentErrorCode:
    return error.value.code


async def test_lists_only_visible_markdown_documents(
    store: WorkspaceContentStore,
) -> None:
    summaries = await store.summaries()
    assert [(s.path, s.title, s.section) for s in summaries] == [
        ("design/01-边界.md", "产品边界", "design")
    ]


async def test_reads_document_with_digest(store: WorkspaceContentStore) -> None:
    document = await store.read("design/01-边界.md")
    assert document.title == "产品边界"
    assert document.sha256 == content_digest("# 产品边界\n\n正文\n")


@pytest.mark.parametrize(
    "path",
    [
        "../secret.md",
        "design/../../x.md",
        "/etc/passwd.md",
        ".obsidian/notes.md",
        "index.mdx",
        "design/",
    ],
)
async def test_rejects_paths_outside_markdown_documents(
    store: WorkspaceContentStore, path: str
) -> None:
    with pytest.raises(WorkspaceDocumentError) as error:
        await store.read(path)
    assert _code(error) is WorkspaceDocumentErrorCode.INVALID_PATH


async def test_does_not_follow_symlinks(
    store: WorkspaceContentStore, tmp_path: Path
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_text("# 外部\n", encoding="utf-8")
    (tmp_path / "design/link.md").symlink_to(outside)
    with pytest.raises(WorkspaceDocumentError) as error:
        await store.read("design/link.md")
    assert _code(error) is WorkspaceDocumentErrorCode.NOT_FOUND


async def test_writes_atomically_when_base_matches(
    store: WorkspaceContentStore, tmp_path: Path
) -> None:
    current = await store.read("design/01-边界.md")
    saved = await store.write(
        "design/01-边界.md", "# 新标题\r\n\r\n内容", current.sha256
    )
    assert saved.title == "新标题"
    assert (tmp_path / "design/01-边界.md").read_text(
        encoding="utf-8"
    ) == "# 新标题\n\n内容\n"
    assert not [p for p in (tmp_path / "design").iterdir() if p.name.endswith(".tmp")]


async def test_rejects_stale_base_without_writing(
    store: WorkspaceContentStore, tmp_path: Path
) -> None:
    with pytest.raises(WorkspaceDocumentError) as error:
        await store.write("design/01-边界.md", "# 覆盖\n", "0" * 64)
    assert _code(error) is WorkspaceDocumentErrorCode.CONFLICT
    assert (
        (tmp_path / "design/01-边界.md")
        .read_text(encoding="utf-8")
        .startswith("# 产品边界")
    )


async def test_never_creates_documents(
    store: WorkspaceContentStore, tmp_path: Path
) -> None:
    with pytest.raises(WorkspaceDocumentError) as error:
        await store.write("design/02-新建.md", "# 新建\n", "0" * 64)
    assert _code(error) is WorkspaceDocumentErrorCode.NOT_FOUND
    assert not (tmp_path / "design/02-新建.md").exists()


async def test_rejects_oversized_content(store: WorkspaceContentStore) -> None:
    current = await store.read("design/01-边界.md")
    with pytest.raises(WorkspaceDocumentError) as error:
        await store.write(
            "design/01-边界.md", "a" * (MAX_DOCUMENT_BYTES + 1), current.sha256
        )
    assert _code(error) is WorkspaceDocumentErrorCode.TOO_LARGE
