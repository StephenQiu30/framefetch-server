"""Review metadata stays outside reader prose and exported files."""

from typing import Literal

from app.services.analysis.rules.content_document import ContentReview
from app.services.analysis.rules.enums import AnalysisValidationCode
from app.services.analysis.rules.errors import AnalysisValidationError

ReviewStatus = Literal["not_reviewed", "passed", "needs_review", "needs_material"]


def editorial_status(history: tuple[ContentReview, ...]) -> ReviewStatus:
    if not history:
        return "not_reviewed"
    latest = history[-1]
    return (
        "needs_material"
        if latest.needs_material
        else "passed"
        if latest.passed
        else "needs_review"
    )


def validate_editorial_review(
    history: tuple[ContentReview, ...], status: ReviewStatus, section_count: int
) -> None:
    ids = {"title", "lead", "closing", "summary", "key-points", "limitations"} | {
        f"section-{index:03d}" for index in range(section_count)
    }
    if (
        len(history) > 2
        or status != editorial_status(history)
        or any(
            item.block_id not in ids for review in history for item in review.findings
        )
    ):
        raise AnalysisValidationError(
            AnalysisValidationCode.INVALID_SCHEMA,
            "editorial review differs from result",
        )
