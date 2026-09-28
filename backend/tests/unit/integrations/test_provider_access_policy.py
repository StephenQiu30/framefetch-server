from dataclasses import replace

import pytest
from app.integrations.media_runner import MediaRunnerRouter
from app.services.downloads.errors import (
    MediaInspectionConfigurationMissing,
    MediaInspectionFailure,
    MediaInspectionPolicyNotAllowed,
)
from app.services.provider_access import (
    ProviderAccessPolicy as Policy,
)
from app.services.provider_access import (
    provider_access_policies,
)
from app.services.provider_types import ProviderAccessMode as Mode
from tests.unit.integrations.test_media_runner_router import FakeClient, context

URL = "https://www.youtube.com/watch?v=owned"


class Sessions:
    """Session records by URL; a record forces the session policy."""

    def __init__(self, policies: dict[str, Policy] | None = None) -> None:
        self.policies = policies or {}

    async def policy_for(self, url: str) -> Policy | None:
        return self.policies.get(url)


def test_public_session_is_a_guest_policy_without_account_privilege() -> None:
    assert Policy.PUBLIC.access_mode is Mode.ANONYMOUS
    assert Policy.PUBLIC_SESSION.access_mode is Mode.GUEST
    assert Policy.OPERATOR_PUBLIC.access_mode is Mode.OPERATOR_MANAGED
    assert provider_access_policies(
        "youtube", (Mode.ANONYMOUS, Mode.GUEST, Mode.OPERATOR_MANAGED)
    ) == (Policy.PUBLIC, Policy.PUBLIC_SESSION, Policy.OPERATOR_PUBLIC)


async def test_explicit_public_never_touches_configured_operator() -> None:
    anonymous = FakeClient(replace(context(Mode.ANONYMOUS), provider_key="youtube"))
    operator = FakeClient(context(Mode.OPERATOR_MANAGED))
    operator.inspect_error = AssertionError("must not access session")
    router = MediaRunnerRouter(anonymous, operator, session_routes=Sessions())  # type: ignore[arg-type]
    result = await router.inspect(URL, access_policy=Policy.PUBLIC)
    assert result.access_context.access_mode is Mode.ANONYMOUS
    assert anonymous.inspected == [URL]
    assert operator.inspected == []


async def test_missing_controlled_route_is_not_anonymous_fallback() -> None:
    anonymous = FakeClient(context(Mode.ANONYMOUS))
    router = MediaRunnerRouter(anonymous)  # type: ignore[arg-type]
    with pytest.raises(MediaInspectionConfigurationMissing):
        await router.inspect(URL, access_policy=Policy.OPERATOR_PUBLIC)
    assert anonymous.inspected == []


async def test_input_only_uses_public_without_touching_configured_sessions() -> None:
    anonymous = FakeClient(replace(context(Mode.ANONYMOUS), provider_key="youtube"))
    operator = FakeClient(context(Mode.OPERATOR_MANAGED))
    operator.inspect_error = AssertionError("must not access session implicitly")
    for session in (None, operator):
        router = MediaRunnerRouter(anonymous, session, session_routes=Sessions())  # type: ignore[arg-type]
        assert (await router.inspect(URL)).access_context.access_mode is Mode.ANONYMOUS
    assert anonymous.inspected == [URL, URL]
    assert operator.inspected == []


async def test_session_record_forces_the_session_route_without_client_policy() -> None:
    anonymous = FakeClient(context(Mode.ANONYMOUS))
    operator = FakeClient(
        replace(context(Mode.OPERATOR_MANAGED), provider_key="youtube")
    )
    router = MediaRunnerRouter(
        anonymous,
        operator,
        session_routes=Sessions({URL: Policy.OPERATOR_PUBLIC}),
    )  # type: ignore[arg-type]
    assert (
        await router.inspect(URL)
    ).access_context.access_mode is Mode.OPERATOR_MANAGED
    assert anonymous.inspected == []
    assert operator.inspected == [URL]
    # A session record can never be bypassed with an explicit public request.
    with pytest.raises(MediaInspectionPolicyNotAllowed):
        await router.inspect(URL, access_policy=Policy.PUBLIC)
    assert anonymous.inspected == []


async def test_session_record_without_a_session_runner_is_a_configuration_gap():
    anonymous = FakeClient(context(Mode.ANONYMOUS))
    router = MediaRunnerRouter(
        anonymous, None, session_routes=Sessions({URL: Policy.OPERATOR_PUBLIC})
    )  # type: ignore[arg-type]
    with pytest.raises(MediaInspectionConfigurationMissing):
        await router.inspect(URL)
    assert anonymous.inspected == []


async def test_unlisted_sites_use_the_session_route_when_a_record_exists() -> None:
    url = "https://media.example.co.uk/v/1"
    anonymous = FakeClient(replace(context(Mode.ANONYMOUS), provider_key="generic"))
    operator = FakeClient(
        replace(context(Mode.OPERATOR_MANAGED), provider_key="generic")
    )
    router = MediaRunnerRouter(
        anonymous, operator, session_routes=Sessions({url: Policy.OPERATOR_PUBLIC})
    )  # type: ignore[arg-type]
    assert (
        await router.inspect(url)
    ).access_context.access_mode is Mode.OPERATOR_MANAGED
    assert operator.inspected == [url]


@pytest.mark.parametrize("requested", [Policy.PUBLIC_SESSION, Policy.PERSONAL_ENTITLED])
async def test_unadmitted_policy_never_reaches_any_runner(requested) -> None:
    anonymous = FakeClient(context(Mode.ANONYMOUS))
    operator = FakeClient(context(Mode.OPERATOR_MANAGED))
    router = MediaRunnerRouter(anonymous, operator, session_routes=Sessions())  # type: ignore[arg-type]
    with pytest.raises(MediaInspectionPolicyNotAllowed):
        await router.inspect(URL, access_policy=requested)
    assert anonymous.inspected == operator.inspected == []


@pytest.mark.parametrize("mismatch", ["mode", "provider"])
async def test_misconfigured_runner_cannot_silently_change_policy(mismatch) -> None:
    wrong = (
        context(Mode.OPERATOR_MANAGED)
        if mismatch == "mode"
        else replace(context(Mode.ANONYMOUS), provider_key="instagram")
    )
    anonymous = FakeClient(wrong)
    router = MediaRunnerRouter(anonymous)  # type: ignore[arg-type]
    with pytest.raises(MediaInspectionFailure, match="context mismatch"):
        await router.inspect(URL, access_policy=Policy.PUBLIC)
    assert anonymous.inspected == [URL]


async def test_public_failure_is_not_retried_with_more_privilege() -> None:
    anonymous = FakeClient(context(Mode.ANONYMOUS))
    anonymous.inspect_error = MediaInspectionFailure()
    operator = FakeClient(context(Mode.OPERATOR_MANAGED))
    router = MediaRunnerRouter(anonymous, operator, session_routes=Sessions())  # type: ignore[arg-type]
    with pytest.raises(MediaInspectionFailure):
        await router.inspect(URL, access_policy=Policy.PUBLIC)
    assert anonymous.inspected == [URL]
    assert operator.inspected == []


@pytest.mark.parametrize("session", [False, True])
async def test_guest_default_yields_only_to_a_session_record(session) -> None:
    url = "https://www.douyin.com/video/7674644830270473609"
    anonymous = FakeClient(replace(context(Mode.ANONYMOUS), provider_key="douyin"))
    guest = FakeClient(
        replace(
            context(Mode.OPERATOR_MANAGED),
            provider_key="douyin",
            access_mode=Mode.GUEST,
        )
    )
    operator = FakeClient(
        replace(context(Mode.OPERATOR_MANAGED), provider_key="douyin")
    )
    router = MediaRunnerRouter(
        anonymous,
        operator,
        guests={"douyin": guest},
        session_routes=Sessions({url: Policy.OPERATOR_PUBLIC} if session else {}),
    )
    expected = Mode.OPERATOR_MANAGED if session else Mode.GUEST
    assert (await router.inspect(url)).access_context.access_mode is expected
    assert anonymous.inspected == []
    assert len(guest.inspected) == (not session)
    assert len(operator.inspected) == session


async def test_guest_failure_does_not_escalate_to_an_account_or_retry_anonymous() -> (
    None
):
    url = "https://www.douyin.com/video/7674644830270473609"
    anonymous = FakeClient(replace(context(Mode.ANONYMOUS), provider_key="douyin"))
    guest = FakeClient(
        replace(
            context(Mode.OPERATOR_MANAGED),
            provider_key="douyin",
            access_mode=Mode.GUEST,
        )
    )
    operator = FakeClient(
        replace(context(Mode.OPERATOR_MANAGED), provider_key="douyin")
    )
    guest.inspect_error = MediaInspectionFailure()
    router = MediaRunnerRouter(
        anonymous, operator, guests={"douyin": guest}, session_routes=Sessions()
    )
    with pytest.raises(MediaInspectionFailure):
        await router.inspect(url)
    assert guest.inspected == [url]
    assert anonymous.inspected == operator.inspected == []
