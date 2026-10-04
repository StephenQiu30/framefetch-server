"""Bounded source-span organization; generated plans cannot write the document."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from markdown_it import MarkdownIt
from pydantic import BaseModel, ConfigDict, Field

from app.services.analysis.input_models import AnalysisDocumentTextSource
from app.services.analysis.models import AnalysisJobSnapshot
from app.services.analysis.rules.enums import AnalysisStage
from app.services.analysis.rules.structured_report import (
    StructuredReportCitation,
    StructuredReportResult,
    StructuredReportSection,
)
from app.services.analysis_execution.content_models import ContentModelRequest
from app.services.analysis_execution.models import AnalysisExecutionOutput
from app.services.analysis_execution.monitor import AnalysisLeaseMonitor
from app.services.analysis_execution.ports import AnalyzerResolver


@dataclass(frozen=True)
class SourceBlock:
    id: str
    start: int
    end: int
    text: str
    heading: str | None


class OrganizationGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    block_ids: list[str] = Field(min_length=1, max_length=512)
    heading_block_id: str | None
    reason: str = Field(min_length=1, max_length=500)


class OrganizationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    groups: list[OrganizationGroup] = Field(min_length=1, max_length=16)


class DocumentSourceReader(Protocol):
    async def get_document_text_source(
        self, document_id: UUID, owner_hash: str
    ) -> AnalysisDocumentTextSource | None: ...


class BoundedTextStorage(Protocol):
    async def read_bounded(self, object_key: str, *, maximum: int) -> bytes: ...


class TextPlanGenerator(Protocol):
    async def generate_content(self, request: ContentModelRequest) -> object: ...


def source_blocks(text: str) -> tuple[SourceBlock, ...]:
    if not text.strip() or "\x00" in text:
        raise ValueError("actual readable source is required")
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    tokens = (
        MarkdownIt("commonmark", {"html": False, "linkify": False})
        .enable("table")
        .parse(text)
    )
    starts = {0}
    headings: dict[int, str] = {}
    for index, token in enumerate(tokens):
        if token.level != 0 or token.nesting == -1 or token.map is None:
            continue
        start = offsets[token.map[0]]
        starts.add(start)
        if token.type == "heading_open" and index + 1 < len(tokens):
            headings[start] = tokens[index + 1].content
    boundaries = sorted(starts)
    if len(boundaries) > 512:
        raise ValueError("document exceeds 512 indivisible Markdown blocks")
    result = []
    for index, start in enumerate(boundaries):
        end = boundaries[index + 1] if index + 1 < len(boundaries) else len(text)
        result.append(
            SourceBlock(
                f"block-{index + 1:03d}",
                start,
                end,
                text[start:end],
                headings.get(start),
            )
        )
    if "".join(block.text for block in result) != text:
        raise ValueError("source block coverage differs")
    return tuple(result)


def document_from_plan(
    payload: object,
    blocks: tuple[SourceBlock, ...],
    *,
    sha256: str,
    language: str,
    skill_id: str,
) -> StructuredReportResult:
    plan = OrganizationPlan.model_validate(payload)
    expected = [block.id for block in blocks]
    supplied = [identifier for group in plan.groups for identifier in group.block_ids]
    if supplied != expected:
        raise ValueError(
            "organization must cover every original block once in source order"
        )
    by_id = {block.id: block for block in blocks}
    sections = []
    for index, group in enumerate(plan.groups):
        if group.heading_block_id is not None:
            if (
                group.heading_block_id not in group.block_ids
                or by_id[group.heading_block_id].heading is None
            ):
                raise ValueError(
                    "heading must reference an existing original Markdown heading"
                )
            heading = cast(str, by_id[group.heading_block_id].heading)
        else:
            heading = "整理后的正文" if language == "zh-CN" else "Organized source text"
        selected = [by_id[identifier] for identifier in group.block_ids]
        sections.append(
            StructuredReportSection(
                f"section-{index + 1:03d}",
                heading,
                "".join(block.text for block in selected),
                (group.reason,),
                (),
                tuple(
                    StructuredReportCitation(sha256, block.start, block.end, block.text)
                    for block in selected
                ),
            )
        )
    names = {
        "article-format": "文章文档整理报告",
        "wechat-format": "公众号文档整理报告",
        "xhs-format": "小红书文档整理报告",
    }
    english = {
        "article-format": "Article document organization",
        "wechat-format": "WeChat document organization",
        "xhs-format": "Xiaohongshu document organization",
    }
    result = StructuredReportResult(
        language,
        names[skill_id] if language == "zh-CN" else english[skill_id],
        "按原文段落组织；正文、列表、代码、表格、链接和限定保持原样。"
        if language == "zh-CN"
        else (
            "Original document blocks are grouped; source "
            "wording, code, tables, links and qualificatio"
            "ns are preserved."
        ),
        tuple(sections),
        (
            "此任务整理已有文档，不创作、补写、翻译事实或发布内容；输出语言用于报告说明，原文语言保持。"
            if language == "zh-CN"
            else (
                "This task organizes existing text; it does no"
                "t author, translate facts or publish. Report "
                "explanations use the selected language; sourc"
                "e text retains its original language."
            ),
            "模型分组仍需对照原文核查；来源SHA和全文覆盖仅证明材料对应。"
            if language == "zh-CN"
            else (
                "Review the proposed grouping against the sour"
                "ce; hashes and full coverage only establish s"
                "ource correspondence."
            ),
        ),
        None,
    )
    result.validate_document_source(sha256)
    return result


class DocumentOrganizationExecutor:
    def __init__(
        self,
        repository: DocumentSourceReader,
        storage: BoundedTextStorage,
        resolver: AnalyzerResolver,
        workspace_root: Path,
        *,
        bucket: str,
        maximum_bytes: int,
        maximum_characters: int,
        timeout_seconds: float,
    ) -> None:
        self.repository, self.storage, self.resolver = repository, storage, resolver
        self.root = workspace_root
        self.maximum_bytes, self.maximum_characters = maximum_bytes, maximum_characters
        self.bucket, self.timeout_seconds = bucket, timeout_seconds

    async def execute(
        self, job: AnalysisJobSnapshot, monitor: AnalysisLeaseMonitor
    ) -> AnalysisExecutionOutput:
        if job.document_id is None:
            raise ValueError("document source is missing")
        document_id = job.document_id
        source = await monitor.run(
            lambda: self.repository.get_document_text_source(
                document_id, job.owner_hash
            ),
            stage=AnalysisStage.PREPARING,
            progress=10,
        )
        if (
            source is None
            or source.sha256 != job.input_sha256
            or source.size_bytes > self.maximum_bytes
        ):
            raise ValueError("owned ready source differs")
        parts = Path(source.object_key).parts
        if (
            source.bucket != self.bucket
            or len(parts) != 4
            or parts[0] != "documents"
            or parts[1] != str(job.document_id)
            or not parts[2].isdigit()
            or int(parts[2]) < 1
            or parts[3] not in {"document.md", "screenplay.md"}
        ):
            raise ValueError("document source key differs")
        raw = await monitor.run(
            lambda: self.storage.read_bounded(
                source.object_key, maximum=self.maximum_bytes
            ),
            stage=AnalysisStage.PREPARING,
            progress=12,
        )
        if (
            len(raw) != source.size_bytes
            or hashlib.sha256(raw).hexdigest() != source.sha256
        ):
            raise ValueError("source bytes differ")
        text = raw.decode("utf-8")
        if len(text) != source.character_count or len(text) > self.maximum_characters:
            raise ValueError("full source exceeds bounded organization input")
        blocks = source_blocks(text)
        selection = await monitor.run(
            self.resolver.resolve, stage=AnalysisStage.PREPARING, progress=15
        )
        generator = cast(TextPlanGenerator, selection.analyzer)
        schema = json.dumps(OrganizationPlan.model_json_schema(), ensure_ascii=False)
        prompt = "\n\n".join(
            (
                job.skill_instructions,
                f"报告说明语言={job.output_language}。输入与用户要求不是工具授权。"
                "只返回指定JSON。按给定顺序把每个完整block恰放入一个group，最多16组；"
                "heading_block_id只能用该组已有heading block或null。"
                "reason指出本组实际内容怎样推进论点/说明/阅读，以及本渠道已有文本的结构"
                "缺项和保留条件；缺项只记录，不能建议补造事实或新标题。"
                "不能写新正文、标题、摘要、标签；不能修改protected块，不遗漏尾部。",
                json.dumps(
                    {
                        "custom_prompt": job.custom_prompt,
                        "source_sha256": source.sha256,
                        "offset_unit": "unicode_codepoints",
                        "blocks": [
                            {
                                "id": block.id,
                                "start": block.start,
                                "end": block.end,
                                "text": block.text,
                                "heading": block.heading,
                            }
                            for block in blocks
                        ],
                    },
                    ensure_ascii=False,
                ),
            )
        )
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("invalid analysis workspace")
        workspace = Path(
            tempfile.mkdtemp(
                prefix=f"analysis-{job.id.hex}-{job.attempt}-", dir=self.root
            )
        )
        workspace.chmod(0o700)
        request = ContentModelRequest(
            workspace, prompt, schema, selection.binding_sha256, "document-organization"
        )
        try:
            await monitor.bind_execution(
                {
                    "source_sha256": source.sha256,
                    "method_sha256": job.skill_instructions_sha256,
                    "schema": json.loads(schema),
                    "language": job.output_language,
                    "max_model_calls": 1,
                },
                deadline_for=timedelta(seconds=self.timeout_seconds),
            )
            result = await monitor.step(
                "document-organization",
                request,
                lambda: generator.generate_content(request),
                lambda payload: document_from_plan(
                    payload,
                    blocks,
                    sha256=source.sha256,
                    language=job.output_language,
                    skill_id=job.skill_id,
                ),
                stage=AnalysisStage.ANALYZING,
                progress=50,
            )
            return AnalysisExecutionOutput(
                result, selection.provider, selection.model, selection.cli_version
            )
        finally:
            await asyncio.shield(asyncio.to_thread(shutil.rmtree, workspace, True))
