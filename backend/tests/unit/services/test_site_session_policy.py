import pytest
from app.integrations.site_session_catalog import known_site_policy, site_policy
from app.services.provider_types import ProviderKey
from app.services.site_sessions import (
    CookieRequirement,
    InvalidSessionSite,
    SessionEntitlement,
    SiteSessionPolicy,
    registrable_site,
)


@pytest.mark.parametrize(
    ("host", "site"),
    [
        ("m.youtube.com", "youtube.com"),
        ("old.reddit.com", "reddit.com"),
        ("A.B.Example.co.uk.", "example.co.uk"),
        ("foo.github.io", "foo.github.io"),
        ("yuanbao.tencent.com", "tencent.com"),
    ],
)
def test_registrable_site_uses_public_suffix_list(host, site):
    assert registrable_site(host) == site


@pytest.mark.parametrize(
    "host",
    [
        "10.0.0.1",
        "127.0.0.1",
        "[::1]",
        "localhost",
        "co.uk",
        "github.io",
        "service.internal",
        "example.com/path",
        "exa mple.com",
        "",
    ],
)
def test_hosts_that_cannot_own_a_session_are_rejected(host):
    with pytest.raises(InvalidSessionSite):
        registrable_site(host)


def test_known_policies_keep_their_entitlement_boundaries():
    youtube = known_site_policy(ProviderKey.YOUTUBE)
    assert youtube is not None and youtube.site == "youtube.com"
    for provider in (ProviderKey.YOUKU, ProviderKey.QQVIDEO):
        policy = known_site_policy(provider)
        assert policy is not None
        assert policy.entitlement is SessionEntitlement.ACCOUNT_ENTITLED_FULL_VIDEO
    wechat = known_site_policy(ProviderKey.WECHAT_CHANNELS)
    assert wechat is not None and wechat.header_plugin is not None
    assert known_site_policy(ProviderKey.BILIBILI) is None
    assert known_site_policy("not-a-provider") is None


def test_unknown_sites_get_a_weak_public_only_policy():
    policy = site_policy("example.co.uk")
    assert policy.provider_key is None
    assert policy.login_url == "https://example.co.uk/"
    assert policy.entitlement is SessionEntitlement.PUBLIC_ONLY
    assert site_policy("youtube.com") is known_site_policy(ProviderKey.YOUTUBE)
    with pytest.raises(InvalidSessionSite):
        site_policy("www.example.co.uk")


def test_cookie_requirements():
    any_of = SiteSessionPolicy(
        "example.com",
        None,
        "https://example.com/",
        required_cookie_names=frozenset({"a", "b"}),
    )
    all_of = SiteSessionPolicy(
        "example.com",
        None,
        "https://example.com/",
        required_cookie_names=frozenset({"a", "b"}),
        requirement=CookieRequirement.ALL,
    )
    unknown = site_policy("example.com")
    assert any_of.accepts(frozenset({"a"})) and not any_of.accepts(frozenset({"c"}))
    assert all_of.accepts(frozenset({"a", "b"})) and not all_of.accepts(
        frozenset({"a"})
    )
    assert unknown.accepts(frozenset({"x"})) and not unknown.accepts(frozenset())


def test_policy_rejects_invalid_declarations():
    with pytest.raises(ValueError):
        SiteSessionPolicy("localhost", None, "https://localhost/")
    with pytest.raises(ValueError):
        SiteSessionPolicy("example.com", None, "http://example.com/")
