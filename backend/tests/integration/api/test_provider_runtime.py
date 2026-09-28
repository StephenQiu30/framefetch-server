from dataclasses import replace

from app.api.deps import get_current_user, get_provider_statuses
from app.integrations.provider_status import configured_provider_statuses
from app.services.auth.models import UserRole
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_types import ProviderAccessMode
from tests.integration.api.test_download_routes import TEST_USER, client
from tests.unit.integrations.test_media_runner_router import context


def test_runtime_requires_admin_before_probing(tmp_path):
    browser, _ = client(tmp_path)

    def unexpected_probe():
        raise AssertionError("ordinary users cannot trigger diagnostics")

    browser.app.dependency_overrides[get_provider_statuses] = unexpected_probe
    with browser:
        response = browser.get("/api/admin/provider-runtime")
    assert response.status_code == 403


def test_admin_runtime_is_allowlisted_and_does_not_expose_context(tmp_path):
    browser, _ = client(tmp_path)
    browser.app.dependency_overrides[get_current_user] = lambda: replace(
        TEST_USER, role=UserRole.ADMIN
    )
    baseline = next(
        view
        for view in configured_provider_statuses(frozenset({"youtube"}))
        if view.key == "youtube"
    )
    # A site session record selects the account policy at request time.
    baseline = replace(
        baseline, default_access_policy_id=ProviderAccessPolicy.OPERATOR_PUBLIC
    )
    runtime = replace(
        context(ProviderAccessMode.OPERATOR_MANAGED),
        credential_version_id="private-revision-do-not-expose",
        egress_affinity_id="private-egress-do-not-expose",
    )
    browser.app.dependency_overrides[get_provider_statuses] = lambda: (
        replace(baseline, runtime_context=runtime),
    )
    with browser:
        response = browser.get("/api/admin/provider-runtime")
    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["access_policy_id"] == ProviderAccessPolicy.OPERATOR_PUBLIC
    assert item["context_available"] is True
    assert item["source_state"] == "revision_observed"
    assert item["evidence_state"] == "missing"
    assert "private-" not in response.text
    assert "credential_version_id" not in response.text
    assert "egress_affinity_id" not in response.text
