from dataclasses import replace

from app.api.deps import get_current_user
from app.integrations.media_runner_models import MediaRunnerClientError
from app.schemas.engine_catalog import EngineCandidateResponse, EngineCatalogResponse
from app.services.auth.models import UserRole
from tests.integration.api.test_download_routes import TEST_USER, client


def test_catalog_admin_boundary_runs_before_the_runner(tmp_path):
    browser, _ = client(tmp_path)

    async def unexpected():
        raise AssertionError("non-admin must not reach the Runner")

    browser.app.state.services.engine_catalog_reader = unexpected
    with browser:
        assert (
            browser.get("/api/admin/provider-runtime/engine-catalog").status_code == 403
        )


def test_admin_receives_candidates_without_platform_success_claim(tmp_path):
    browser, _ = client(tmp_path)
    browser.app.dependency_overrides[get_current_user] = lambda: replace(
        TEST_USER, role=UserRole.ADMIN
    )

    async def read():
        return EngineCatalogResponse(
            engine_version="test-version",
            engine_commit="a" * 40,
            expected_engine_commit="b" * 40,
            pin_matches=False,
            bundled_plugins_sha256="c" * 64,
            manifest_id="d" * 64,
            candidates=(
                EngineCandidateResponse(
                    key="Unknown", name="Unknown site", upstream_working=True
                ),
            ),
        )

    browser.app.state.services.engine_catalog_reader = read
    with browser:
        response = browser.get("/api/admin/provider-runtime/engine-catalog")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]
    assert not data["pin_matches"]
    assert "download_available" not in response.text
    assert data["candidates"][0]["key"] == "Unknown"


def test_runner_failure_is_a_service_outage_not_identity_expiry(tmp_path):
    browser, _ = client(tmp_path)
    browser.app.dependency_overrides[get_current_user] = lambda: replace(
        TEST_USER, role=UserRole.ADMIN
    )

    async def failed():
        raise MediaRunnerClientError("private_runner_detail", 401)

    browser.app.state.services.engine_catalog_reader = failed
    with browser:
        response = browser.get("/api/admin/provider-runtime/engine-catalog")
    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"
    assert "private_runner_detail" not in response.text
