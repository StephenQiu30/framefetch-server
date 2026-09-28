from dataclasses import replace
from types import SimpleNamespace

import pytest
from app.integrations.media_runner import MediaRunnerRouter
from app.integrations.site_session_catalog import SiteSessionRoutes
from app.services.downloads.errors import (
    MediaInspectionConfigurationMissing,
    MediaInspectionFailure,
    MediaInspectionPolicyNotAllowed,
    MediaInspectionSessionNotReady,
)
from app.services.provider_access import ProviderAccessPolicy as Policy
from app.services.provider_types import ProviderAccessMode as Mode
from app.services.site_sessions import SiteSessionState as State
from tests.unit.integrations.test_media_runner_router import FakeClient, context

URL = "https://youtube.com/watch?v=owned"


class States:
    def __init__(self, state):
        self.state = state

    async def get(self, site):
        return None if self.state is None else SimpleNamespace(state=self.state)


@pytest.mark.parametrize("state", [None, *State])
async def test_no_state_can_fall_back_to_anonymous(state):
    client = FakeClient(context(Mode.OPERATOR_MANAGED))
    routes = SiteSessionRoutes(States(state))
    router = MediaRunnerRouter(client, session_routes=routes)
    assert await router.resolve_access_policy(URL) is Policy.OPERATOR_PUBLIC
    if state is State.READY:
        await router.inspect(URL)
        assert client.inspected == [URL]
    else:
        error = (
            MediaInspectionConfigurationMissing
            if state in {None, State.REVOKED, State.RESEED_REQUIRED}
            else MediaInspectionSessionNotReady
        )
        with pytest.raises(error):
            await router.inspect(URL)
        assert client.inspected == []


@pytest.mark.parametrize(
    "policy", [Policy.PUBLIC, Policy.PUBLIC_SESSION, Policy.PERSONAL_ENTITLED]
)
async def test_explicit_retired_or_wrong_entitlement_policy_is_rejected(policy):
    client = FakeClient(context(Mode.OPERATOR_MANAGED))
    router = MediaRunnerRouter(
        client, session_routes=SiteSessionRoutes(States(State.READY))
    )
    with pytest.raises(MediaInspectionPolicyNotAllowed):
        await router.inspect(URL, access_policy=policy)
    assert client.inspected == []


async def test_unknown_site_is_not_promoted_by_arbitrary_cookies():
    routes = SiteSessionRoutes(States(State.READY))
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
    router = MediaRunnerRouter(
        FakeClient(wrong), session_routes=SiteSessionRoutes(States(State.READY))
    )
    with pytest.raises(MediaInspectionFailure, match="context mismatch"):
        await router.inspect(URL)
