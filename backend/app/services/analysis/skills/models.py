from __future__ import annotations

from dataclasses import dataclass

from app.services.analysis.rules.enums import AnalysisInputKind, AnalysisResultContract


@dataclass(frozen=True, slots=True)
class AnalysisSkill:
    id: str
    display_name: str
    description: str
    default_prompt: str
    instructions: str
    instructions_sha256: str
    order: int
    input_kinds: tuple[AnalysisInputKind, ...]
    result_contract: AnalysisResultContract
