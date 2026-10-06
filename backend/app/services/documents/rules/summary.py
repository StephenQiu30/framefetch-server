from __future__ import annotations

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt

from app.services.documents.rules.screenplay import ScreenplayScene
from app.services.documents.rules.structure import ScreenplayElementKind

_LIST_ITEM = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+\S")


@dataclass(frozen=True, slots=True)
class DocumentParseSummary:
    page_count: int | None
    paragraph_count: int
    heading_count: int
    list_item_count: int
    table_count: int
    dialogue_block_count: int

    def __post_init__(self) -> None:
        values = (
            self.paragraph_count,
            self.heading_count,
            self.list_item_count,
            self.table_count,
            self.dialogue_block_count,
        )
        if self.page_count is not None and self.page_count <= 0:
            raise ValueError("document page count must be positive")
        if self.paragraph_count <= 0 or any(value < 0 for value in values[1:]):
            raise ValueError("document parse summary counts are invalid")


def summarize_document(
    text: str,
    scenes: tuple[ScreenplayScene, ...],
    *,
    page_count: int | None = None,
    table_count: int = 0,
    markdown: bool = False,
) -> DocumentParseSummary:
    non_empty_lines = tuple(line for line in text.splitlines() if line.strip())
    kinds = tuple(element.kind for scene in scenes for element in scene.elements)
    heading_count = sum(
        kind in {ScreenplayElementKind.HEADING, ScreenplayElementKind.SECTION}
        for kind in kinds
    )
    list_item_count = sum(bool(_LIST_ITEM.match(line)) for line in non_empty_lines)
    if markdown:
        tokens = (
            MarkdownIt("commonmark", {"html": False, "linkify": False})
            .enable("table")
            .parse(text)
        )
        heading_count = sum(token.type == "heading_open" for token in tokens)
        list_item_count = sum(token.type == "list_item_open" for token in tokens)
        table_count = sum(token.type == "table_open" for token in tokens)
    return DocumentParseSummary(
        page_count=page_count,
        paragraph_count=len(non_empty_lines),
        heading_count=heading_count,
        list_item_count=list_item_count,
        table_count=table_count,
        dialogue_block_count=sum(
            kind is ScreenplayElementKind.DIALOGUE for kind in kinds
        ),
    )
