from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.services.download_execution.errors import classify_runner_failure
from app.services.downloads.errors import (
    ApplicationError,
    ApplicationErrorCode,
    MediaInspectionFailure,
)
from app.services.downloads.rules.content_restrictions import ContentRestriction
from app.services.downloads.rules.enums import DownloadErrorCode
from app.services.provider_failures import ProviderFailure
from app.workers.runner.errors import RunnerFailure
from tests.unit.services.fakes import FakeRepository
from tests.unit.services.test_inspect_media import OWNER, runner_result, use_case


@pytest.mark.parametrize("reason", list(ContentRestriction))
async def test_recognized_restriction_is_terminal_and_never_creates_inspection(
    reason, monkeypatch
) -> None:
    repository = FakeRepository()
    inspect, runner, _ = use_case(repository, runner_result())
    monkeypatch.setattr(
        runner,
        "inspect",
        AsyncMock(
            side_effect=MediaInspectionFailure(
                failure=ProviderFailure.for_code(reason.value)
            )
        ),
    )
    with pytest.raises(ApplicationError) as caught:
        await inspect("https://www.bilibili.com/video/BV1xx411c7mD", OWNER, "paid-1")
    assert caught.value.code is ApplicationErrorCode.CONTENT_PROTECTED
    assert repository.inspection_commands == []
    assert (
        classify_runner_failure(RunnerFailure(reason.value, status=422))
        is DownloadErrorCode.CONTENT_PROTECTED
    )
