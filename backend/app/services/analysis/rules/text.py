from __future__ import annotations

from app.services.analysis.rules.enums import AnalysisValidationCode
from app.services.analysis.rules.errors import AnalysisValidationError


def required_text(
    value: str, field: str, *, maximum: int = 8_000, allow_empty: bool = False
) -> str:
    if not isinstance(value, str):
        raise AnalysisValidationError(
            AnalysisValidationCode.INVALID_TEXT, f"{field} must be a string"
        )
    normalized = value.strip()
    if (not normalized and not allow_empty) or len(normalized) > maximum:
        raise AnalysisValidationError(
            AnalysisValidationCode.INVALID_TEXT,
            f"{field} must contain 1 to {maximum} characters",
        )
    return normalized


def identifier(value: str, field: str) -> str:
    normalized = required_text(value, field, maximum=128)
    if normalized != value or any(character.isspace() for character in normalized):
        raise AnalysisValidationError(
            AnalysisValidationCode.INVALID_TEXT,
            f"{field} cannot contain whitespace",
        )
    return normalized


def non_negative_integer(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AnalysisValidationError(
            AnalysisValidationCode.INVALID_TIME_RANGE,
            f"{field} must be a non-negative integer",
        )
    return value
