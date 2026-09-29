import pytest
from app.integrations.site_session_catalog import (
    site_target,
    site_target_for_url,
)
from app.services.provider_types import ProviderAccessMode, ProviderKey
from app.services.site_sessions import known_site_policy
from app.workers.runner.provider_registry import provider_profile_for_key


@pytest.mark.parametrize(
    ("url", "site", "provider"),
    [
        ("https://youtu.be/BWst4tlkNdc", "youtube.com", ProviderKey.YOUTUBE),
        ("https://m.youtube.com/watch?v=1", "youtube.com", ProviderKey.YOUTUBE),
        ("https://v.douyin.com/abc/", "douyin.com", ProviderKey.DOUYIN),
        ("https://old.reddit.com/r/a/", "reddit.com", ProviderKey.REDDIT),
        ("https://weixin.qq.com/sph/abc", "weixin.qq.com", ProviderKey.WECHAT_CHANNELS),
        ("https://v.qq.com/x/cover/a.html", "v.qq.com", ProviderKey.QQVIDEO),
    ],
)
def test_known_provider_urls_map_to_their_session(url, site, provider):
    target = site_target_for_url(url)
    assert target.site == site and target.policy.provider_key is provider
    assert target.cookie_domains == frozenset(
        provider_profile_for_key(provider).cookie_domain_allowlist
    )


def test_unknown_sites_are_scoped_by_registrable_domain():
    target = site_target_for_url("https://media.sub.example.co.uk/v/1")
    assert target.site == "example.co.uk"
    assert target.policy.provider_key is None
    assert target.cookie_domains == frozenset({"example.co.uk"})
    # A different qq.com host is not captured by the Tencent Video session.
    assert site_target_for_url("https://m.qq.com/v").site == "qq.com"


def test_every_known_policy_is_an_account_capable_provider():
    for provider in ProviderKey:
        policy = known_site_policy(provider)
        if policy is None:
            continue
        profile = provider_profile_for_key(provider)
        assert ProviderAccessMode.OPERATOR_MANAGED in profile.access_modes
        assert profile.cookie_domain_allowlist
        assert site_target(policy.site).policy is policy
