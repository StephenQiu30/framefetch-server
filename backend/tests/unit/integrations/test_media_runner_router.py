"""One Runner handles media work without a policy/admission/retry facade."""

from unittest.mock import AsyncMock

import pytest
from app.integrations.media_runner import MediaRunnerRouter
from app.integrations.media_runner_models import MediaRunnerClientError
from app.services.downloads.errors import MediaInspectionFailure
from tests.unit.workers.runner.helpers import download_request


async def test_inspection_returns_the_runner_result_without_another_attempt():
    runner = AsyncMock()
    router = MediaRunnerRouter(runner)
    result = await router.inspect("https://vimeo.com/1")
    assert result is runner.inspect.return_value
    runner.inspect.assert_awaited_once_with(
        "https://vimeo.com/1", task_id=None, deadline=None
    )


async def test_inspection_failure_preserves_execution_facts():
    runner = AsyncMock()
    error = MediaRunnerClientError("challenge", 422)
    runner.inspect.side_effect = error
    with pytest.raises(MediaInspectionFailure) as caught:
        await MediaRunnerRouter(runner).inspect("https://vimeo.com/1")
    assert caught.value.failure is error.failure
    runner.inspect.assert_awaited_once()


async def test_download_keeps_execution_context_and_runtime_cancellation():
    runner = AsyncMock()
    router = MediaRunnerRouter(runner)
    context = download_request().execution_context.to_domain()
    result = await router.download(
        "task",
        "https://vimeo.com/1",
        None,
        expected_provider_media_id="1",
        expected_extractor_key="Vimeo",
        execution_context=context,
    )
    assert result is runner.download.return_value
    assert runner.download.call_args.kwargs["execution_context"] is context
    await router.cancel("task")
    await router.close()
    runner.cancel.assert_awaited_once_with("task")
    runner.close.assert_awaited_once()
