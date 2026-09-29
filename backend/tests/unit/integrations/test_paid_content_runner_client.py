from pathlib import Path

import httpx
import pytest
from app.integrations.media_runner import MediaRunnerHttpClient
from app.services.downloads.errors import MediaInspectionPaidContentRestricted
from app.services.downloads.rules.content_restrictions import ContentRestriction


@pytest.mark.parametrize("reason", list(ContentRestriction))
async def test_runner_client_preserves_known_content_reason(reason) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/runtime":
            return httpx.Response(200, json={"instance_id": "0" * 32})
        return httpx.Response(
            422, json={"error": {"code": reason.value, "message": "restricted"}}
        )

    async with httpx.AsyncClient(
        base_url="http://runner", transport=httpx.MockTransport(respond)
    ) as http:
        client = MediaRunnerHttpClient(
            base_url="http://runner",
            secret=b"s" * 32,
            workspace_root=Path("."),
            inspect_timeout_seconds=1,
            download_timeout_seconds=1,
            client=http,
        )
        with pytest.raises(MediaInspectionPaidContentRestricted) as caught:
            await client.inspect("https://www.douyin.com/video/1234567890123456789")
    assert caught.value.reason is reason
