from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from app.services.analysis.rules.enums import AnalysisValidationCode
from app.services.analysis.rules.errors import AnalysisValidationError
from app.services.analysis.rules.result_models import AnalysisLimits


@dataclass(slots=True)
class ParseContext:
    limits: AnalysisLimits
    total_characters: int = 0

    def mapping(
        self,
        value: object,
        path: str,
        required: set[str],
        optional: set[str] | None = None,
    ) -> dict[str, object]:
        if not isinstance(value, dict) or any(
            not isinstance(key, str) for key in value
        ):
            self.invalid(f"{path} must be an object")
        mapping = cast(dict[str, object], value)
        allowed = required | (optional or set())
        if not required.issubset(mapping) or set(mapping) - allowed:
            self.invalid(f"{path} fields do not match the strict schema")
        return mapping

    def array(self, value: object, path: str, *, allow_empty: bool) -> list[object]:
        if not isinstance(value, list):
            self.invalid(f"{path} must be an array")
        array = cast(list[object], value)
        if (not allow_empty and not array) or len(
            array
        ) > self.limits.max_collection_items:
            code = (
                AnalysisValidationCode.INVALID_SCHEMA
                if not array
                else AnalysisValidationCode.LIMIT_EXCEEDED
            )
            raise AnalysisValidationError(code, f"{path} has an invalid item count")
        return array

    def text(
        self,
        value: object,
        path: str,
        *,
        maximum: int | None = None,
        allow_empty: bool = False,
    ) -> str:
        limit = maximum or self.limits.max_string_characters
        if (
            not isinstance(value, str)
            or (not value.strip() and not allow_empty)
            or len(value.strip()) > limit
        ):
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_TEXT, f"{path} is invalid"
            )
        result = value.strip()
        self.total_characters += len(result)
        if self.total_characters > self.limits.max_total_characters:
            raise AnalysisValidationError(
                AnalysisValidationCode.LIMIT_EXCEEDED,
                "analysis result text exceeds the total limit",
            )
        return result

    def integer(self, value: object, path: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_TIME_RANGE, f"{path} is invalid"
            )
        return value

    def preserved_text(
        self, value: object, path: str, *, maximum: int | None = None
    ) -> str:
        limit = maximum or self.limits.max_string_characters
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_TEXT, f"{path} is invalid"
            )
        self.total_characters += len(value)
        if self.total_characters > self.limits.max_total_characters:
            raise AnalysisValidationError(
                AnalysisValidationCode.LIMIT_EXCEEDED,
                "analysis result text exceeds the total limit",
            )
        return value

    @staticmethod
    def invalid(detail: str) -> None:
        raise AnalysisValidationError(AnalysisValidationCode.INVALID_SCHEMA, detail)
