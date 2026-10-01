from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.api.deps import get_current_user
from app.core.config import Settings
from app.main import create_app
from app.services.auth.models import CurrentUser, UserRole
from app.services.downloads.errors import ApplicationError, ApplicationErrorCode
from app.services.downloads.rules.enums import DownloadStatus
from fastapi.testclient import TestClient
from tests.integration.api.fakes import (
    DISCOVERY_ID,
    FORMAT_ID,
    INSPECTION_ID,
    ITEM_REF,
    JOB_ID,
    StubUseCase,
    download_view,
    source_discovery_use_cases,
    use_cases,
)

TEST_USER = CurrentUser(
    id=JOB_ID,
    username="video_user",
    email="user@example.com",
    role=UserRole.USER,
    created_at=datetime(2026, 8, 6, tzinfo=UTC),
    updated_at=datetime(2026, 8, 6, tzinfo=UTC),
)


class FakeDownloadStorage:
    def iter_download(
        self,
        _object_key: str,
        *,
        offset: int,
        length: int,
        chunk_size: int = 1024 * 1024,
    ):
        del chunk_size
        return iter((b"artifact"[offset : offset + length],))


def client(tmp_path: Path) -> tuple[TestClient, dict[str, StubUseCase]]:
    app = create_app(
        Settings(
            app_env="test",
            _env_file=None,
            runner_operator_base_urls={},
        )
    )
    container, stubs = use_cases()
    discovery_container, discovery_stubs = source_discovery_use_cases()
    app.state.services.download_use_cases = container
    app.state.services.source_discovery_use_cases = discovery_container
    stubs.update(discovery_stubs)
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    return TestClient(app), stubs


def test_download_use_cases_are_resolved_from_app_state(tmp_path: Path) -> None:
    app = create_app(Settings(app_env="test"))
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/inspections",
            headers={"Idempotency-Key": "inspect-1"},
            json={
                "source": {"kind": "public_url", "url": "https://media.example/owned"}
            },
        )

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"


def test_explicit_policy_reaches_use_case_but_unknown_policy_does_not(
    tmp_path: Path,
) -> None:
    test_client, stubs = client(tmp_path)
    with test_client:
        result = test_client.post(
            "/api/inspections",
            headers={"Idempotency-Key": "policy"},
            json={
                "source": {
                    "kind": "public_url",
                    "url": "https://media.example/video",
                },
            },
        )
        assert result.status_code == 201
        assert stubs["inspect"].calls[0][1] == {}
        rejected = test_client.post(
            "/api/inspections",
            headers={"Idempotency-Key": "unknown"},
            json={
                "source": {
                    "kind": "public_url",
                    "url": "https://media.example/video",
                    "access_policy_id": "bypass",
                },
            },
        )
    assert rejected.status_code == 422
    assert len(stubs["inspect"].calls) == 1


def test_inspection_routes_use_stable_session_and_hide_hints(tmp_path: Path) -> None:
    test_client, stubs = client(tmp_path)
    with test_client:
        created = test_client.post(
            "/api/inspections",
            headers={"Idempotency-Key": "inspect-1"},
            json={
                "source": {"kind": "public_url", "url": "https://media.example/owned"}
            },
        )
        fetched = test_client.get(f"/api/inspections/{INSPECTION_ID}")

    assert created.status_code == 201
    assert fetched.status_code == 200
    payload = created.json()["data"]
    assert payload["id"] == str(INSPECTION_ID)
    assert "hints" not in payload["formats"][0]["plan"]
    assert "provider_hints" not in created.text
    create_owner = stubs["inspect"].calls[0][0][1]
    get_owner = stubs["get_inspection"].calls[0][0][1]
    assert create_owner == get_owner
    assert len(str(create_owner)) == 64


def test_source_discovery_requires_explicit_item_selection(tmp_path: Path) -> None:
    test_client, stubs = client(tmp_path)
    with test_client:
        created = test_client.post(
            "/api/source-discoveries",
            headers={"Idempotency-Key": "discover-1"},
            json={
                "kind": "wechat_official_account_article",
                "url": "https://mp.weixin.qq.com/s/article_123",
            },
        )
        fetched = test_client.get(f"/api/source-discoveries/{DISCOVERY_ID}")
        selected = test_client.post(
            "/api/inspections",
            headers={"Idempotency-Key": "inspect-item-1"},
            json={
                "source": {
                    "kind": "discovered_item",
                    "discovery_id": str(DISCOVERY_ID),
                    "item_ref": str(ITEM_REF),
                }
            },
        )

    assert created.status_code == selected.status_code == 201
    assert fetched.status_code == 200
    assert created.headers["location"] == f"/api/source-discoveries/{DISCOVERY_ID}"
    assert created.json()["data"]["items"][0]["item_ref"] == str(ITEM_REF)
    assert stubs["inspect"].calls == []
    selected_args = stubs["inspect_discovered"].calls[0][0]
    assert selected_args[:2] == (DISCOVERY_ID, ITEM_REF)
    assert len(str(selected_args[2])) == 64


def test_thumbnail_route_returns_private_image_with_integrity_headers(
    tmp_path: Path,
) -> None:
    test_client, stubs = client(tmp_path)
    with test_client:
        response = test_client.get(f"/api/inspections/{INSPECTION_ID}/thumbnail")

    assert response.status_code == 200
    assert response.content == b"image"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, max-age=3600"
    assert response.headers["etag"] == f'"{"a" * 64}"'
    assert stubs["get_thumbnail"].calls[0][0][0] == INSPECTION_ID
    assert len(str(stubs["get_thumbnail"].calls[0][0][1])) == 64


def test_download_thumbnail_route_returns_generated_first_frame(
    tmp_path: Path,
) -> None:
    test_client, stubs = client(tmp_path)
    with test_client:
        response = test_client.get(f"/api/downloads/{JOB_ID}/thumbnail")

    assert response.status_code == 200
    assert response.content == b"first-frame"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["etag"] == f'"{"b" * 64}"'
    assert stubs["get_download_thumbnail"].calls[0][0][0] == JOB_ID


def test_download_routes_delegate_with_session_owner(tmp_path: Path) -> None:
    test_client, stubs = client(tmp_path)
    body = {"inspection_id": str(INSPECTION_ID), "format_id": str(FORMAT_ID)}
    with test_client:
        created = test_client.post(
            "/api/downloads",
            headers={"Idempotency-Key": "download-1"},
            json=body,
        )
        fetched = test_client.get(f"/api/downloads/{JOB_ID}")
        deleted = test_client.delete(f"/api/downloads/{JOB_ID}")
        cancelled = test_client.post(f"/api/downloads/{JOB_ID}/cancel")
        retried = test_client.post(
            f"/api/downloads/{JOB_ID}/retry",
            headers={"Idempotency-Key": "retry-1"},
        )
        issued = test_client.post(
            f"/api/downloads/{JOB_ID}/download-url", params={"preview": True}
        )

    assert created.status_code == 201
    assert deleted.status_code == 204
    assert created.headers["location"] == f"/api/downloads/{JOB_ID}"
    assert fetched.status_code == cancelled.status_code == issued.status_code == 200
    assert retried.status_code == 201
    assert retried.headers["location"] == f"/api/downloads/{JOB_ID}"
    assert created.json()["data"]["status"] == "queued"
    assert cancelled.json()["data"]["status"] == "cancelled"
    assert issued.json()["data"]["url"] == "https://objects.example/token"
    assert issued.json()["data"]["filename"] == "video.mp4"
    assert stubs["issue_url"].calls[0][1] == {
        "preview": True,
        "use_browser_proxy": False,
    }
    owners = [
        stubs["create"].calls[0][0][-2],
        *(
            stubs[name].calls[0][0][-1]
            for name in ("get", "delete", "cancel", "issue_url")
        ),
        stubs["retry"].calls[0][0][-2],
    ]
    assert len(set(owners)) == 1
    assert stubs["retry"].calls[0][0][-1] == "retry-1"


def test_admin_download_route_forwards_admin_admission_context(tmp_path: Path) -> None:
    test_client, stubs = client(tmp_path)
    test_client.app.dependency_overrides[get_current_user] = lambda: replace(
        TEST_USER, role=UserRole.ADMIN
    )
    body = {"inspection_id": str(INSPECTION_ID), "format_id": str(FORMAT_ID)}

    with test_client:
        response = test_client.post(
            "/api/downloads",
            headers={"Idempotency-Key": "admin-download-1"},
            json=body,
        )

    assert response.status_code == 201
    assert stubs["create"].calls[0][1]["quota"].exempt is True


def test_download_file_route_streams_an_owned_range(tmp_path: Path) -> None:
    test_client, stubs = client(tmp_path)
    stubs["get"].result = download_view(title="Owned video")
    test_client.app.state.services.download_storage = FakeDownloadStorage()

    with test_client:
        response = test_client.get(
            f"/api/downloads/{JOB_ID}/file",
            headers={"Range": "bytes=2-5"},
        )

    assert response.status_code == 206
    assert response.content == b"tifa"
    assert response.headers["content-range"] == "bytes 2-5/8"
    assert response.headers["content-length"] == "4"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-disposition"] == (
        'attachment; filename="Owned video.mp4"'
    )


def test_download_file_head_returns_preview_metadata(tmp_path: Path) -> None:
    test_client, stubs = client(tmp_path)
    stubs["get"].result = download_view(title="Owned video")
    test_client.app.state.services.download_storage = FakeDownloadStorage()

    with test_client:
        response = test_client.head(
            f"/api/downloads/{JOB_ID}/file",
            params={"preview": True},
        )

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["content-length"] == "8"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-disposition"] == "inline"
    assert response.headers["etag"] == f'"{"c" * 64}"'


def test_download_history_route_supports_filters_and_returns_public_fields(
    tmp_path: Path,
) -> None:
    test_client, stubs = client(tmp_path)
    with test_client:
        response = test_client.get(
            "/api/downloads/history",
            params={
                "page": 2,
                "page_size": 10,
                "status": "succeeded",
                "search": "Owned",
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["items"][0] == {
        "id": str(JOB_ID),
        "title": "Owned video",
        "thumbnail_url": f"/api/inspections/{INSPECTION_ID}/thumbnail",
        "format_name": "1080p MP4",
        "status": "succeeded",
        "progress": 100,
        "error_code": None,
        "created_at": "2026-08-06T10:00:00Z",
        "updated_at": "2026-08-06T10:00:00Z",
        "finished_at": "2026-08-06T10:00:00Z",
        "file_available": False,
        "source_kind": "remote_provider",
        "source_label": "链接下载",
    }
    assert response.json()["data"]["summary"] == {
        "total": 1,
        "succeeded": 1,
        "active": 0,
        "failed": 0,
    }
    _, kwargs = stubs["history"].calls[0]
    assert kwargs == {
        "page": 2,
        "page_size": 10,
        "status": DownloadStatus.SUCCEEDED,
        "search": "Owned",
    }


def test_provider_status_distinguishes_registered_verified_and_unsupported(
    tmp_path: Path,
) -> None:
    test_client, _ = client(tmp_path)
    with test_client:
        response = test_client.get("/api/providers")

    assert response.status_code == 200
    from app.workers.runner.provider_registry import current_provider_registry

    declared = {p.key: p for p in current_provider_registry().profiles}
    items = {item["key"]: item for item in response.json()["data"]["items"]}
    assert len(items) == len(declared) + 1
    for key, item in items.items():
        assert item["registered"] is True
        assert "access_modes" not in item
        assert "download_available" not in item
        if key in declared:
            assert item["identity"] == declared[key].identity.value
            assert item["status"] == declared[key].support_status.value
    assert items["wechat_official_account_article"]["status"] == "unknown"
    assert not {"acfun", "rutube", "vk", "dailymotion", "niconico"} & items.keys()
    assert "peertube" not in items
    assert all(
        sensitive not in response.text.casefold()
        for sensitive in ("credential_version", "egress_affinity", "po_token")
    )


def test_creation_contract_rejects_missing_headers_and_invalid_bodies(
    tmp_path: Path,
) -> None:
    test_client, stubs = client(tmp_path)
    with test_client:
        missing = test_client.post(
            "/api/inspections",
            json={
                "source": {"kind": "public_url", "url": "https://media.example/video"}
            },
        )
        extra = test_client.post(
            "/api/inspections",
            headers={"Idempotency-Key": "key"},
            json={
                "source": {"kind": "public_url", "url": "https://media.example/video"},
                "cookie": "secret",
            },
        )
        too_long = test_client.post(
            "/api/inspections",
            headers={"Idempotency-Key": "key"},
            json={
                "source": {
                    "kind": "public_url",
                    "url": "https://example.com/" + "a" * 4_100,
                }
            },
        )
        invalid_uuid = test_client.post(
            "/api/downloads",
            headers={"Idempotency-Key": "key"},
            json={"inspection_id": "bad", "format_id": str(FORMAT_ID)},
        )

    assert {
        missing.status_code,
        extra.status_code,
        too_long.status_code,
        invalid_uuid.status_code,
    } == {422}
    assert stubs["inspect"].calls == []
    assert stubs["create"].calls == []


def test_application_errors_are_error_envelopes(tmp_path: Path) -> None:
    test_client, stubs = client(tmp_path)
    stubs["get"].error = ApplicationError(ApplicationErrorCode.NOT_FOUND)
    with test_client:
        response = test_client.get(f"/api/downloads/{JOB_ID}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["code"] == "not_found"
    assert set(response.json()) == {"code", "message", "data"}


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (ApplicationErrorCode.IDEMPOTENCY_CONFLICT, 409),
        (ApplicationErrorCode.INVALID_URL, 422),
        (ApplicationErrorCode.EXTRACTOR_BROKEN, 502),
        (ApplicationErrorCode.TRANSIENT, 503),
        (ApplicationErrorCode.LOGIN_REQUIRED, 403),
        (ApplicationErrorCode.CONTENT_UNAVAILABLE, 422),
        (ApplicationErrorCode.INVALID_INPUT, 422),
    ],
)
def test_inspection_errors_have_stable_http_mapping(
    tmp_path: Path,
    code: ApplicationErrorCode,
    status: int,
) -> None:
    test_client, stubs = client(tmp_path)
    stubs["inspect"].error = ApplicationError(code)
    with test_client:
        response = test_client.post(
            "/api/inspections",
            headers={"Idempotency-Key": "inspect-1"},
            json={
                "source": {"kind": "public_url", "url": "https://media.example/owned"}
            },
        )

    assert response.status_code == status
    assert response.json()["code"] == code.value
