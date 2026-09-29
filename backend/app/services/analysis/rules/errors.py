from __future__ import annotations

from app.services.analysis.rules.enums import AnalysisValidationCode


class AnalysisValidationError(ValueError):
    def __init__(self, code: AnalysisValidationCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")
