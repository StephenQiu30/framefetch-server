"""Select stage context from the immutable method snapshot, never live files."""

from app.services.analysis_execution.editorial_plan import has_stage, stage_method


def content_method(snapshot: str, *, review: bool) -> str:
    result = stage_method(snapshot, "review" if review else "draft")
    if not has_stage(snapshot, "review" if review else "draft"):
        raise ValueError("content method is missing its stage")
    return result
