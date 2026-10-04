from __future__ import annotations

import pytest
from app.integrations.ai_cli import prompt
from app.repositories.analysis import repository_serialization
from app.services.analysis import report
from app.services.analysis.rules import model_schema as schema
from app.services.analysis.rules import result_parser
from app.services.analysis.rules.contracts import (
    RESULT_CONTRACTS,
    contract_for,
    contract_for_kind,
    contracts_for_input,
)
from app.services.analysis.rules.enums import (
    AnalysisInputKind,
    AnalysisResultContract,
    AnalysisResultKind,
)


def test_every_contract_is_registered_once() -> None:
    assert {item.contract for item in RESULT_CONTRACTS} == set(AnalysisResultContract)
    assert {item.kind for item in RESULT_CONTRACTS} == set(AnalysisResultKind)
    for item in RESULT_CONTRACTS:
        assert contract_for(item.contract.value) is item
        assert contract_for_kind(item.kind.value) is item


def test_every_layer_dispatches_every_registered_contract() -> None:
    """A new contract must be wired into each layer, not only the enum."""
    kinds = {item.kind for item in RESULT_CONTRACTS}
    assert set(repository_serialization._FROM_DOCUMENT) == kinds
    assert set(report._RENDERERS) == kinds
    video = contracts_for_input(AnalysisInputKind.VIDEO)
    assert set(result_parser._VIDEO_PARSERS) == video
    assert set(schema._VIDEO_SCHEMAS) == video
    assert set(prompt._VIDEO_PROMPTS) == video


def test_input_kinds_partition_the_contracts() -> None:
    video = contracts_for_input(AnalysisInputKind.VIDEO)
    screenplay = contracts_for_input(AnalysisInputKind.SCREENPLAY)
    assert video.isdisjoint(screenplay)
    content = contracts_for_input(AnalysisInputKind.CONTENT)
    assert content.isdisjoint(video | screenplay)
    assert video | screenplay | content == set(AnalysisResultContract)


def test_video_dispatch_rejects_screenplay_contracts() -> None:
    with pytest.raises(ValueError, match="not a video result contract"):
        schema.analysis_output_schema(
            "zh-CN", AnalysisResultContract.SCREENPLAY_ANALYSIS
        )
