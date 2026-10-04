from hashlib import sha256
from io import BytesIO

import pytest
from app.services.creation.catalog import CAPABILITIES, get_capability
from app.services.creation.execution import (
    execute_deterministic,
    validate_model_output,
)
from app.services.creation.sources import extract_document
from docx import Document


def material(text: str) -> dict[str, object]:
    return {
        "id": "source-one",
        "revision_id": "revision-one",
        "kind": "text",
        "title": "原创测试",
        "text": text,
        "sha256": sha256(text.encode()).hexdigest(),
        "rights_statement": "原创",
        "confirmed": True,
    }


def test_format_preserves_markdown_code_quotes_links_and_hard_breaks() -> None:
    text = (
        "# 原稿\r\n\r\n> 引用  \r\n[链接](https://example.org)\r\n\r\n"
        '```python\r\n x = "  "\r\n```'
    )
    output = execute_deterministic("article-edit", [material(text)], {})
    assert output.text == text.replace("\r\n", "\n")
    assert "  \n" in output.text
    assert ' x = "  "' in output.text


def test_catalog_has_original_frozen_methods_for_seventeen_product_tasks() -> None:
    assert len(CAPABILITIES) == 12
    assert len({cap.id for cap in CAPABILITIES}) == 12
    assert all(len(cap.method_sha256) == 64 for cap in CAPABILITIES)
    assert get_capability("xhs-cards").execution_kind == "local"


def test_source_positions_must_match_pinned_version() -> None:
    source = material("这是原创材料，未经验证的数字不能当作事实。")
    value = {
        "body": "候选文章",
        "summary": "待核查",
        "structured": {
            "sections": [],
            "characters": [],
            "findings": [],
            "unresolved": [],
        },
        "media_evidence": [],
        "warnings": [],
        "evidence": [
            {
                "material_id": source["id"],
                "sha256": source["sha256"],
                "start": 0,
                "end": 6,
                "quote": "这是原创材料",
                "claim": "材料由作者提供",
                "status": "observation",
            }
        ],
    }
    result = validate_model_output(value, [source])
    assert result.data["review_status"] == "needs_review"
    value["evidence"][0]["quote"] = "假的引用"  # type: ignore[index]
    with pytest.raises(ValueError, match="pinned material"):
        validate_model_output(value, [source])


def test_direct_channel_input_has_editable_pages_but_no_fake_image() -> None:
    output = execute_deterministic("xhs-cards", [material("第一段\n\n第二段")], {})
    assert len(output.data["pages"]) == 2  # type: ignore[arg-type]
    assert output.data["image_status"] == "not_rendered"
    assert (
        execute_deterministic("wechat-package", [material("正文")], {}).text == "正文"
    )


def test_docx_source_order_preserved_and_article_has_no_scene_count_rule() -> None:
    document = Document()
    document.add_paragraph("前文")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "甲"
    table.cell(0, 1).text = "乙"
    document.add_paragraph("后文")
    buffer = BytesIO()
    document.save(buffer)
    assert (
        extract_document("稿件.docx", buffer.getvalue(), kind="text")
        == "前文\n\n甲\t乙\n\n后文"
    )
    text = "\n".join("INT. ROOM - DAY" for _ in range(61))
    assert extract_document("文章.md", text.encode(), kind="text") == text
    with pytest.raises(ValueError, match="60 scenes"):
        extract_document("剧本.fountain", text.encode(), kind="script")


def test_invalid_sources_fail_without_ocr_or_silent_decode_repair() -> None:
    with pytest.raises(UnicodeDecodeError):
        extract_document("draft.txt", b"\xff", kind="text")
    with pytest.raises(ValueError, match="30000"):
        extract_document("draft.txt", ("中" * 30001).encode(), kind="text")
