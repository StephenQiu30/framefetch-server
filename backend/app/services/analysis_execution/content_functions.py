"""Allowlisted source functions for a single immutable content task.

The workflow dispatches these calls deterministically before each model step.
Providers receive the returned data, never filesystem paths or arbitrary tools.
"""

from typing import Literal

from pydantic import Field

from app.services.analysis.rules.content_document import (
    ContentModel,
    ContentSourceSet,
    Identifier,
)


class MaterialArguments(ContentModel):
    material_id: Identifier
    segment_id: str = Field(pattern=r"^segment-[0-9]{3}$")


class ReadMaterialCall(ContentModel):
    name: Literal["read_material"]
    arguments: MaterialArguments


class ContentFunctions:
    def __init__(self, source: ContentSourceSet) -> None:
        self._source = source
        self._remaining = 88

    def list_materials(self) -> list[dict[str, object]]:
        segments = self._source.segments()
        return [
            {
                "id": item.id,
                "title": item.title,
                "role": item.role,
                "segments": [
                    f"segment-{index:03d}" for index in range(len(segments[item.id]))
                ],
            }
            for item in self._source.materials
        ]

    def dispatch(self, payload: object) -> str:
        call = ReadMaterialCall.model_validate(payload)
        if self._remaining <= 0:
            raise ValueError("source function budget exhausted")
        self._remaining -= 1
        return self._source.read_segment(
            call.arguments.material_id, call.arguments.segment_id
        )

    def material_context(self) -> list[dict[str, object]]:
        result = []
        for material in self.list_materials():
            segments = material["segments"]
            assert isinstance(segments, list)
            result.append(
                {
                    **material,
                    "segments": [
                        {
                            "id": segment,
                            "text": self.dispatch(
                                {
                                    "name": "read_material",
                                    "arguments": {
                                        "material_id": material["id"],
                                        "segment_id": segment,
                                    },
                                }
                            ),
                        }
                        for segment in segments
                    ],
                }
            )
        return result
