from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.integration.api.test_download_routes import (
    JOB_ID,
    TEST_USER,
    FakeDownloadStorage,
    client,
)


def test_processed_file_head_range_and_owner(tmp_path):
    test_client, _ = client(tmp_path)
    repo = SimpleNamespace(
        artifact=AsyncMock(
            return_value=(
                SimpleNamespace(
                    id=JOB_ID, size_bytes=8, sha256="a" * 64, object_key="processed"
                ),
                None,
            )
        )
    )
    test_client.app.state.services.watermark_repository = repo
    test_client.app.state.services.download_storage = FakeDownloadStorage()
    path = f"/api/watermarks/{JOB_ID}/file"
    with test_client:
        head = test_client.head(path)
        whole = test_client.get(path)
        partial = test_client.get(path, headers={"Range": "bytes=1-3"})
        invalid = test_client.get(path, headers={"Range": "bytes=20-30"})
    assert head.status_code == whole.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == "8"
    assert whole.content == b"artifact"
    assert whole.headers["content-type"] == "video/mp4"
    assert "attachment" in whole.headers["content-disposition"]
    assert partial.status_code == 206
    assert partial.content == b"rti"
    assert partial.headers["content-range"] == "bytes 1-3/8"
    assert invalid.status_code == 416
    repo.artifact.assert_awaited_with(JOB_ID, TEST_USER.owner_hash)
