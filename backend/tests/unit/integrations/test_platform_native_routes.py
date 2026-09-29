from dataclasses import replace

import pytest
from app.integrations.media_runner import MediaRunnerRouter
from app.integrations.site_session_catalog import SiteSessionRoutes
from app.services.downloads.errors import MediaInspectionPolicyNotAllowed
from app.services.provider_access import NATIVE_PUBLIC_PROVIDERS, ProviderAccessPolicy
from app.services.provider_types import ProviderAccessMode
from app.workers.runner.provider_registry import provider_profile_for_key
from tests.unit.integrations.test_media_runner_router import FakeClient, context


@pytest.mark.parametrize("provider", sorted(NATIVE_PUBLIC_PROVIDERS))
async def test_native_platforms_have_one_fixed_route_without_session_io(provider):
    profile = provider_profile_for_key(provider)
    url = f"https://{sorted(profile.hosts)[0]}/"
    routes = SiteSessionRoutes()
    assert await routes.policy_for(url) is ProviderAccessPolicy.PUBLIC
    await routes.ensure_ready(url)
    public = replace(context(ProviderAccessMode.ANONYMOUS), provider_key=provider)
    client = FakeClient(public)
    router = MediaRunnerRouter(client, session_routes=routes)
    assert (await router.inspect(url)).access_context == public
    with pytest.raises(MediaInspectionPolicyNotAllowed):
        await router.inspect(url, access_policy=ProviderAccessPolicy.OPERATOR_PUBLIC)
    assert client.inspected == [url]


async def test_unknown_host_cannot_enter_native_public_route():
    with pytest.raises(MediaInspectionPolicyNotAllowed):
        await SiteSessionRoutes().policy_for("https://example.org/v")
