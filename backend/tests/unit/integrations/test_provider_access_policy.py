from dataclasses import replace

import pytest
from app.integrations.media_runner import MediaRunnerRouter
from app.integrations.site_session_catalog import SiteSessionRoutes
from app.services.downloads.errors import (
    MediaInspectionFailure,
    MediaInspectionPolicyNotAllowed,
)
from app.services.provider_access import ProviderAccessPolicy as Policy
from app.services.provider_types import ProviderAccessMode as Mode
from tests.unit.integrations.test_media_runner_router import FakeClient, context

URL = "https://youtube.com/watch?v=owned"


async def test_session_sites_always_use_the_session_route():
    # Login state is read live from Chrome by the Runner; a session site never
    # falls back to anonymous.
    client = FakeClient(context(Mode.OPERATOR_MANAGED))
    routes = SiteSessionRoutes()
    router = MediaRunnerRouter(client, session_routes=routes)
    assert await router.resolve_access_policy(URL) is Policy.OPERATOR_PUBLIC
    await router.inspect(URL)
    assert client.inspected == [URL]


@pytest.mark.parametrize(
    "policy", [Policy.PUBLIC, Policy.PUBLIC_SESSION, Policy.PERSONAL_ENTITLED]
)
async def test_explicit_retired_or_wrong_entitlement_policy_is_rejected(policy):
    client = FakeClient(context(Mode.OPERATOR_MANAGED))
    router = MediaRunnerRouter(client, session_routes=SiteSessionRoutes())
    with pytest.raises(MediaInspectionPolicyNotAllowed):
        await router.inspect(URL, access_policy=policy)
    assert client.inspected == []


async def test_unknown_site_is_not_promoted_by_arbitrary_cookies():
    routes = SiteSessionRoutes()
    with pytest.raises(MediaInspectionPolicyNotAllowed):
        await routes.policy_for("https://media.example.com/video/1")


@pytest.mark.parametrize(
    "wrong",
    [
        context(Mode.ANONYMOUS),
        replace(context(Mode.OPERATOR_MANAGED), provider_key="instagram"),
    ],
)
async def test_context_mismatch_is_rejected(wrong):
    router = MediaRunnerRouter(FakeClient(wrong), session_routes=SiteSessionRoutes())
    with pytest.raises(MediaInspectionFailure, match="context mismatch"):
        await router.inspect(URL)
