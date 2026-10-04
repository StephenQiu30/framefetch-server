"""Frozen legacy report payloads for owner-scoped history readers."""

from app.services.analysis.rules.content_document import ContentSourceSet


def source(document_type="article"):
    return ContentSourceSet.model_validate(
        {
            "materials": [
                {
                    "id": "notes",
                    "title": "试用笔记",
                    "text": (
                        "旋紧杯盖后，杯子短暂倒置，桌面未见水滴。未做长时间携带测试。"
                    ),
                }
            ],
            "brief": {"document_type": document_type, "purpose": "介绍这次观察"},
        }
    )


def draft(document_type="article"):
    return {
        "document_type": document_type,
        "language": "zh-CN",
        "title": None if document_type == "post" else "旋紧杯盖之后",
        "blocks": [
            {
                "id": "opening",
                "type": "paragraph",
                "text": "杯盖旋紧后，杯子短暂倒置，桌面上没有看到水滴。",
            },
            {
                "id": "closing",
                "type": "paragraph",
                "text": "这次只看了短暂倒置，长时间携带还没有测试。",
            },
        ],
        "evidence_index": [
            {
                "block_id": "opening",
                "material_id": "notes",
                "segment_id": "segment-000",
                "quote": "桌面未见水滴",
            }
        ],
    }


def review(major=False, needs_material=False):
    return {
        "needs_material": needs_material,
        "findings": [
            {
                "block_id": "closing",
                "severity": "major",
                "category": "missing_material" if needs_material else "expression",
                "problem": "结尾可更自然",
                "correction": "收窄到这次观察",
            }
        ]
        if major or needs_material
        else [],
    }
