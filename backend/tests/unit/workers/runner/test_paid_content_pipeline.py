from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from app.services.downloads.rules.content_restrictions import ContentRestriction
from app.workers.runner.commands import MediaCommands
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.process import ProcessResult
from app.workers.runner.provider_errors import (
    ProviderFailureContext,
    classify_provider_failure,
)
from app.workers.runner.service import MediaRunnerService
from helpers import download_request, settings


@pytest.mark.parametrize("reason", list(ContentRestriction))
def test_content_markers_have_priority_over_login_hints(reason) -> None:
    context = ProviderFailureContext(
        "bilibili", "https://www.bilibili.com/video/BV1xx411c7mD", False
    )
    assert classify_provider_failure(
        context, f"FrameFetch {reason.value}; login required".encode()
    ) == ("content_unavailable", 422)


async def test_successful_ytdlp_preview_warning_is_still_rejected(
    tmp_path: Path,
) -> None:
    supervisor = AsyncMock()
    supervisor.run.return_value = ProcessResult(
        0,
        b'{"formats": []}',
        b"WARNING: This is a supporter-only video, only the preview will be extracted",
        False,
        False,
    )
    commands = MediaCommands(settings(tmp_path), supervisor)
    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://www.bilibili.com/video/BV1xx411c7mD", tmp_path)
    assert caught.value.code == "content_unavailable"


@pytest.mark.parametrize("reason", list(ContentRestriction))
async def test_queued_download_rechecks_and_stops_before_media_access(
    tmp_path: Path, monkeypatch, reason
) -> None:
    inspect = AsyncMock(side_effect=RunnerFailure(reason.value, status=422))
    monkeypatch.setattr(MediaCommands, "inspect", inspect)
    supervisor = AsyncMock()
    service = MediaRunnerService(settings(tmp_path), supervisor=supervisor)
    with pytest.raises(RunnerFailure) as caught:
        await service.download(download_request())
    assert caught.value.code == reason.value
    inspect.assert_awaited_once()
    supervisor.run.assert_not_awaited()
