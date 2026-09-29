"""The single registry of analysis result contracts.

A contract fixes the output shape a Skill selects: its stored result kind, the
input it accepts and the result type the strict parser produces. Parsers,
serializers and report renderers are keyed by these identities instead of
repeating type checks, so a new contract is added in one place per layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.analysis.rules.enums import (
    AnalysisInputKind,
    AnalysisResultContract,
    AnalysisResultKind,
)
from app.services.analysis.rules.result_models import (
    VideoAnalysisResult,
    VideoArticleResult,
)
from app.services.analysis.rules.result_types import AnalysisResult
from app.services.analysis.rules.screenplay_results import (
    ScreenplayAnalysisResult,
    ScreenplayRewriteResult,
)
from app.services.analysis.rules.structured_report import StructuredReportResult


@dataclass(frozen=True, slots=True)
class ResultContract:
    contract: AnalysisResultContract
    kind: AnalysisResultKind
    input_kind: AnalysisInputKind
    result_type: type[AnalysisResult]
    # Rewrite results are stored in the target language they produce.
    language_field: str = "language"

    def language(self, result: AnalysisResult) -> str:
        value = getattr(result, self.language_field)
        assert isinstance(value, str)
        return value


RESULT_CONTRACTS: tuple[ResultContract, ...] = (
    ResultContract(
        AnalysisResultContract.VIDEO_VISUAL_ANALYSIS,
        AnalysisResultKind.VIDEO_VISUAL_ANALYSIS,
        AnalysisInputKind.VIDEO,
        VideoAnalysisResult,
    ),
    ResultContract(
        AnalysisResultContract.VIDEO_ARTICLE,
        AnalysisResultKind.VIDEO_ARTICLE,
        AnalysisInputKind.VIDEO,
        VideoArticleResult,
    ),
    ResultContract(
        AnalysisResultContract.SCREENPLAY_ANALYSIS,
        AnalysisResultKind.SCREENPLAY_ANALYSIS,
        AnalysisInputKind.SCREENPLAY,
        ScreenplayAnalysisResult,
    ),
    ResultContract(
        AnalysisResultContract.SCREENPLAY_REWRITE,
        AnalysisResultKind.SCREENPLAY_REWRITE,
        AnalysisInputKind.SCREENPLAY,
        ScreenplayRewriteResult,
        language_field="target_language",
    ),
    ResultContract(
        AnalysisResultContract.STRUCTURED_REPORT,
        AnalysisResultKind.STRUCTURED_REPORT,
        AnalysisInputKind.VIDEO,
        StructuredReportResult,
    ),
)

_BY_CONTRACT = {item.contract: item for item in RESULT_CONTRACTS}
_BY_KIND = {item.kind: item for item in RESULT_CONTRACTS}
_BY_TYPE = {item.result_type: item for item in RESULT_CONTRACTS}
if not len(_BY_CONTRACT) == len(_BY_KIND) == len(_BY_TYPE) == len(RESULT_CONTRACTS):
    raise RuntimeError("analysis result contracts must be unique")
if set(_BY_CONTRACT) != set(AnalysisResultContract) or set(_BY_KIND) != set(
    AnalysisResultKind
):
    raise RuntimeError("every analysis result contract must be registered")


def contract_for(value: AnalysisResultContract | str) -> ResultContract:
    return _BY_CONTRACT[AnalysisResultContract(value)]


def contract_for_kind(value: AnalysisResultKind | str) -> ResultContract:
    return _BY_KIND[AnalysisResultKind(value)]


def contract_for_result(result: AnalysisResult) -> ResultContract:
    try:
        return _BY_TYPE[type(result)]
    except KeyError:
        raise TypeError("unsupported analysis result") from None


def contracts_for_input(
    input_kind: AnalysisInputKind,
) -> frozenset[AnalysisResultContract]:
    return frozenset(
        item.contract for item in RESULT_CONTRACTS if item.input_kind is input_kind
    )
