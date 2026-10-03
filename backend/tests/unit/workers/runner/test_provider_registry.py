from dataclasses import replace

import pytest
from app.services.provider_types import (
    EgressRoute,
    Layer,
    ProviderCapability,
    ProviderIdentity,
    ProviderKey,
    ProviderProfileVersion,
    ProviderSupportStatus,
)
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import (
    ProviderProfile,
    ProviderRegistry,
    configure_provider_instances,
    default_provider_registry,
    provider_profile,
    provider_request,
)


def provider_request_url(url: str) -> str:
    return provider_request(url).request_url


def provider_command_args(url: str) -> tuple[str, ...]:
    return provider_request(url).profile.command_args


def test_uses_public_vimeo_player_endpoint_for_canonical_video() -> None:
    assert (
        provider_request_url("https://vimeo.com/76979871?share=copy")
        == "https://player.vimeo.com/video/76979871"
    )
    assert (
        provider_request_url("https://www.vimeo.com/76979871/")
        == "https://player.vimeo.com/video/76979871"
    )


@pytest.mark.parametrize(
    "url",
    (
        "https://www.dailymotion.com/video/xAb123",
        "https://dailymotion.com/video/xAb123/",
        "http://www.dailymotion.com:80/video/xAb123?playlist=xList&autoPlay=1",
        "https://www.dailymotion.com:443/video/xAb123?utm_source=share#player",
        "https://dai.ly/xAb123",
        "http://dai.ly/xAb123/?playlist=xList&start=30#share",
    ),
)
def test_dailymotion_shares_bind_one_video_without_playlist_context(url: str) -> None:
    request = provider_request(url)
    assert request.source_url == url
    assert request.request_url == "https://www.dailymotion.com/video/xAb123"
    assert request.profile.key == ProviderKey.DAILYMOTION


def test_dailymotion_declares_only_anonymous_public_single_video() -> None:
    profile = default_provider_registry().profile_for_key(ProviderKey.DAILYMOTION)
    assert profile.version == ProviderProfileVersion.DAILYMOTION
    assert profile.hosts == frozenset(
        {"dailymotion.com", "www.dailymotion.com", "dai.ly"}
    )
    assert not profile.host_suffixes
    assert profile.capabilities == frozenset({ProviderCapability.SINGLE_VIDEO})
    assert profile.ladder == (Layer.L1,)
    assert profile.egress_route is EgressRoute.GLOBAL
    assert profile.identity is ProviderIdentity.NONE
    assert not profile.cookie_domain_allowlist
    assert profile.identity_origin is None
    assert profile.content_scope == "public"
    assert profile.support_status is ProviderSupportStatus.UNKNOWN


@pytest.mark.parametrize(
    "url",
    (
        "https://www.dailymotion.com/",
        "https://www.dailymotion.com/playlist/xList",
        "https://www.dailymotion.com/user/creator",
        "https://www.dailymotion.com/channel/news",
        "https://www.dailymotion.com/search/video",
        "https://www.dailymotion.com/live/xAb123",
        "https://www.dailymotion.com/video/",
        "https://www.dailymotion.com/video/xAb123/extra",
        "https://www.dailymotion.com/video/xAb123_title",
        "https://www.dailymotion.com/video/xAb%31%32%33",
        "https://www.dailymotion.com/embed/video/xAb123",
        "https://www.dailymotion.com/player.html?video=xAb123",
        "https://dai.ly/playlist/xList",
        "https://dai.ly/xAb123/extra",
        "https://www.dailymotion.com:8443/video/xAb123",
        "https://www.dailymotion.com:bad/video/xAb123",
        "https://www.dailymotion.com:/video/xAb123",
        "https://user:password@www.dailymotion.com/video/xAb123",
        "ftp://www.dailymotion.com/video/xAb123",
        "https://www.dailymotion.com/video/xAb123\n",
        "https://www.dailymotion.com/video/xAb123?tracking=a b",
    ),
)
def test_dailymotion_rejects_non_single_video_or_invalid_urls(url: str) -> None:
    with pytest.raises(RunnerFailure) as captured:
        provider_request_url(url)
    assert captured.value.code == "provider_unsupported"


@pytest.mark.parametrize(
    "url",
    (
        "https://geo.dailymotion.com/video/xAb123",
        "https://touch.dailymotion.com/video/xAb123",
        "https://media.dailymotion.com/video/xAb123",
        "https://www.dai.ly/xAb123",
        "https://media.dai.ly/xAb123",
        "https://www.dailymotion.com./video/xAb123",
        "https://dai.ly./xAb123",
    ),
)
def test_dailymotion_unapproved_hosts_cannot_enter_generic(url: str) -> None:
    with pytest.raises(RunnerFailure) as captured:
        provider_profile(url)
    assert captured.value.code == "provider_unsupported"
    with pytest.raises(RunnerFailure) as captured:
        provider_request_url(url)
    assert captured.value.code == "provider_unsupported"


@pytest.mark.parametrize(
    "host",
    ("acfun.cn", "vk.com", "geo.dailymotion.com", "media.dai.ly"),
)
def test_registered_other_profiles_do_not_override_closed_platform_domains(
    host: str,
) -> None:
    registry = ProviderRegistry(
        (ProviderProfile("peertube", "PeerTube", frozenset({host})),)
    )
    with pytest.raises(RunnerFailure) as captured:
        registry.resolve(f"https://{host}/w/AbCdEfGhIjKlMnOpQrStUv")
    assert captured.value.code == "provider_unsupported"


def test_youtube_uses_the_managed_mweb_pot_route() -> None:
    profile = provider_profile("https://www.youtube.com/watch?v=owned")

    assert profile.version == ProviderProfileVersion.YOUTUBE
    assert profile.client_profile == "youtube:mweb"
    assert profile.yt_dlp_retry_count == 0
    assert not hasattr(profile, "inspection_attempts")


def test_builtin_profiles_use_centralized_provider_identifiers() -> None:
    profiles = ProviderRegistry(default_provider_registry().profiles).profiles

    provider_keys = {key.value for key in ProviderKey}
    profile_versions = {version.value for version in ProviderProfileVersion}

    assert all(profile.key in provider_keys for profile in profiles)
    assert all(profile.version in profile_versions for profile in profiles)


def test_registry_rejects_negative_yt_dlp_retry_budget() -> None:
    profile = ProviderProfile(
        key="invalid",
        display_name="Invalid",
        hosts=frozenset({"invalid.example.com"}),
        yt_dlp_retry_count=-1,
    )

    with pytest.raises(ValueError, match="invalid retry policy"):
        ProviderRegistry((profile,))


@pytest.mark.parametrize(
    "url",
    (
        "https://vimeo.com/76979871",
        "https://www.tiktok.com/@nba/video/7492902606063275294",
        "https://x.com/canghe/status/2087368911625052411",
        "https://www.instagram.com/reel/DbKfjdhTMAY/",
        "https://www.facebook.com/reel/1195289147628387",
        "https://clips.twitch.tv/FaintLightGullWholeWheat",
        "https://www.pinterest.com/pin/664281013778109217/",
        "https://weibo.com/7827771738/N4xlMvjhI",
        "https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEniNoMPwAAYYWtidGhudGZpAX1TKn0JAX1TKnXJAAAAAA",
        "https://www.linkedin.com/posts/the-mathworks_2_what-is-mathworks-cloud-center-activity-7151241570371948544-4Gu7",
        "https://t.me/europa_press/613",
        "https://kick.com/spreen/clips/clip_01J8RGZRKHXHXXKJEHGRM932A5",
        "https://www.tumblr.com/maskofthedragon/626907179849564160/mona-talking-in-english",
    ),
)
def test_verified_provider_status(url: str) -> None:
    assert provider_profile(url).support_status is ProviderSupportStatus.UNKNOWN


def test_hongguo_official_share_is_a_single_video_profile() -> None:
    profile = provider_profile("https://novelquickapp.com/s/YMc-jWnOo1U/")

    assert profile.key == "hongguo_web"
    assert profile.version == "hongguo-official-share"
    assert profile.support_status is ProviderSupportStatus.UNKNOWN
    assert profile.capabilities == frozenset({ProviderCapability.SINGLE_VIDEO})


def test_preserves_unlisted_and_non_vimeo_urls() -> None:
    assert (
        provider_request_url("https://vimeo.com/76979871/private-hash")
        == "https://vimeo.com/76979871/private-hash"
    )


@pytest.mark.parametrize(
    "url",
    (
        "https://weixin.qq.com/example",
        "https://weixin.qq.com/sph/AFWYoXF5Bw?scene=1",
        "https://weixin.qq.com/sph/AFWYoXF5Bw#fragment",
    ),
)
def test_wechat_channels_rejects_non_public_single_video_paths(url: str) -> None:
    with pytest.raises(RunnerFailure) as captured:
        provider_request_url(url)
    assert captured.value.code == "provider_unsupported"


def test_new_social_profiles_have_versioned_single_media_boundaries() -> None:
    expected = {
        "https://www.snapchat.com/spotlight/example_1": (
            "snapchat-spotlight",
            "yt-dlp-default",
        ),
        "https://www.linkedin.com/posts/example-activity-1234567890-example": (
            "linkedin-public-post",
            "yt-dlp-default",
        ),
        "https://t.me/example_channel/613": (
            "telegram-public-channel-post",
            "yt-dlp-default",
        ),
        "https://kick.com/example/clips/clip_01ABCDEF": (
            "kick-public-clip",
            "yt-dlp-default",
        ),
        "https://www.tumblr.com/example/1234567890/video": (
            "tumblr-public-video-post",
            "chrome-136-macos-15",
        ),
    }

    assert {
        url: (provider_profile(url).version, provider_profile(url).client_profile)
        for url in expected
    } == expected


@pytest.mark.parametrize(
    "url",
    (
        "https://www.snapchat.com/add/example",
        "https://www.linkedin.com/company/example/",
        "https://t.me/example_channel",
        "https://kick.com/example",
        "https://kick.com/example/videos/12345678-abcd",
        "https://www.tumblr.com/example",
    ),
)
def test_new_social_profiles_reject_non_single_video_paths(url: str) -> None:
    with pytest.raises(RunnerFailure) as captured:
        provider_request_url(url)
    assert captured.value.code == "provider_unsupported"


def test_normalizes_kick_clip_query_to_the_clip_endpoint() -> None:
    assert (
        provider_request_url("https://kick.com/example?clip=clip_01ABCDEF")
        == "https://kick.com/example/clips/clip_01ABCDEF"
    )


def test_strips_linkedin_share_tracking_from_public_video_posts() -> None:
    assert provider_request_url(
        "https://www.linkedin.com/feed/update/urn:li:activity:7016901149999955968/"
        "?utm_source=share&utm_medium=member_desktop"
    ) == ("https://www.linkedin.com/feed/update/urn:li:activity:7016901149999955968/")


def test_normalizes_douyin_shared_video_urls() -> None:
    assert (
        provider_request_url(
            "https://www.douyin.com/jingxuan?modal_id=7647907920252949425"
        )
        == "https://www.douyin.com/video/7647907920252949425"
    )
    assert (
        provider_request_url("https://www.douyin.com/share/video/7647907920252949425")
        == "https://www.douyin.com/video/7647907920252949425"
    )
    assert provider_request_url("https://www.douyin.com/video/123") == (
        "https://www.douyin.com/video/123"
    )
    assert (
        provider_request_url("https://media.example.com/76979871")
        == "https://media.example.com/76979871"
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    (
        (
            "https://m.tiktok.com/@creator/video/123?is_from_webapp=1#share",
            "https://www.tiktok.com/@creator/video/123",
        ),
        (
            "https://www.tiktok.com/embed/123?lang=en",
            "https://www.tiktok.com/embed/123",
        ),
        ("https://vm.tiktok.com/ZTR45GpSF/?share=1", "https://vm.tiktok.com/ZTR45GpSF"),
        (
            "https://tiktok.com/t/ZTRC5xgJp?source=share",
            "https://www.tiktok.com/t/ZTRC5xgJp",
        ),
    ),
)
def test_tiktok_normalizes_only_supported_public_video_urls(
    url: str,
    expected: str,
) -> None:
    assert provider_request_url(url) == expected


@pytest.mark.parametrize(
    "url",
    (
        "https://www.tiktok.com/about",
        "https://www.tiktok.com/@creator",
        "https://www.tiktok.com/@creator/photo/123",
        "https://www.tiktok.com/player/v1/123",
        "https://m.tiktok.com/share/live/123",
    ),
)
def test_tiktok_rejects_urls_that_could_fall_through_to_generic_webpage(
    url: str,
) -> None:
    with pytest.raises(RunnerFailure) as captured:
        provider_request_url(url)

    assert captured.value.code == "provider_unsupported"


@pytest.mark.parametrize(
    "url",
    [
        "https://v.youku.com/v_show/id_XOTUxMzg4NDMy.html",
        "https://v.qq.com/x/page/q326831cny0.html",
    ],
)
def test_personal_clear_streams_enable_authenticated_media_probe(url):
    profile = provider_profile(url)
    assert profile.identity == "required"
    assert profile.content_scope == "personal_full"
    assert profile.probe_authenticated_media is True


def test_targets_douyin_request_impersonation_without_hidden_retries() -> None:
    url = "https://www.douyin.com/video/123"

    assert provider_command_args(url) == (
        "--impersonate",
        "Chrome-136:Macos-15",
    )
    assert not hasattr(provider_request(url).profile, "inspection_attempts")

    assert provider_profile(url).cookie_domain_allowlist == frozenset(
        {"douyin.com", "iesdouyin.com"}
    )
    assert provider_profile(url).probe_authenticated_media is True
    assert provider_profile(url).probe_media_duration is True

    short_url = "https://v.douyin.com/example/"
    assert provider_command_args(short_url) == (
        "--impersonate",
        "Chrome-136:Macos-15",
    )
    assert not hasattr(provider_request(short_url).profile, "inspection_attempts")


def test_targets_xiaohongshu_short_links_with_browser_impersonation() -> None:
    for url in (
        "https://xhslink.com/m/AbC123",
        "https://www.xiaohongshu.com/explore/abc123",
    ):
        assert provider_command_args(url) == (
            "--impersonate",
            "Chrome-136:Macos-15",
        )
        assert not hasattr(provider_request(url).profile, "inspection_attempts")

        assert provider_profile(url).support_status is ProviderSupportStatus.UNKNOWN
        assert provider_profile(url).cookie_domain_allowlist == frozenset(
            {"xiaohongshu.com"}
        )


def test_tumblr_leaves_retries_to_durable_plan() -> None:
    url = (
        "https://www.tumblr.com/maskofthedragon/"
        "626907179849564160/mona-talking-in-english"
    )

    assert not hasattr(provider_request(url).profile, "inspection_attempts")


def test_slow_public_extractors_have_no_internal_inspection_retry() -> None:
    telegram = "https://t.me/europa_press/613"
    kick = "https://kick.com/spreen/clips/clip_01J8RGZRKHXHXXKJEHGRM932A5"

    assert not hasattr(provider_request(telegram).profile, "inspection_attempts")

    assert not hasattr(provider_request(kick).profile, "inspection_attempts")


def test_normalizes_legacy_tumblr_blog_posts_to_the_current_public_page() -> None:
    url = (
        "https://maskofthedragon.tumblr.com/post/"
        "626907179849564160/mona-talking-in-english"
    )

    assert provider_profile(url).key == "tumblr"
    assert provider_request_url(url) == (
        "https://www.tumblr.com/maskofthedragon/"
        "626907179849564160/mona-talking-in-english"
    )


def test_hongguo_series_page_requires_an_explicit_episode() -> None:
    url = "https://hongguoduanju.com/detail?series_id=7543112466771741721"

    assert provider_profile(url).key == "hongguo_web"
    with pytest.raises(RunnerFailure) as captured:
        provider_request_url(url)
    assert captured.value.code == "provider_media_unsupported"


def test_hongguo_player_requires_a_single_episode_identity() -> None:
    assert provider_request_url(
        "https://hongguoduanju.com/player/7543112466771741721/7614027168942672958"
    ).endswith("/7543112466771741721/7614027168942672958")

    with pytest.raises(RunnerFailure) as captured:
        provider_request_url("https://hongguoduanju.com/player/7543112466771741721")
    assert captured.value.code == "provider_unsupported"


def test_normalizes_kuaishou_public_videos_and_uses_android_impersonation() -> None:
    url = "https://www.kuaishou.com/short-video/3x888mrikrur4g2"

    assert provider_request_url(url) == (
        "https://v.m.chenzhongtech.com/fw/photo/3x888mrikrur4g2"
    )
    assert provider_command_args(url) == (
        "--impersonate",
        "Chrome-131:Android-14",
    )
    assert not hasattr(provider_request(url).profile, "inspection_attempts")

    assert provider_request_url("https://v.kuaishou.com/8qIlZu") == (
        "https://v.kuaishou.com/8qIlZu"
    )


@pytest.mark.parametrize(
    "url",
    (
        "https://www.acfun.cn/v/ac35457073",
        "https://rutube.ru/video/0123456789abcdef0123456789abcdef",
        "https://m.vk.ru/clip123_456/",
        "https://geo.dailymotion.com/video/1",
        "https://www.nicovideo.jp/watch/sm1",
    ),
)
def test_removed_platforms_fail_closed_instead_of_using_generic(url: str) -> None:
    with pytest.raises(RunnerFailure) as captured:
        provider_profile(url)
    assert captured.value.code == "provider_unsupported"

    with pytest.raises(RunnerFailure) as captured:
        provider_request_url(url)
    assert captured.value.code == "provider_unsupported"


def test_registry_classifies_mainstream_platform_hosts() -> None:
    expected = {
        "youtube.com": "youtube",
        "b23.tv": "bilibili",
        "www.douyin.com": "douyin",
        "vm.tiktok.com": "tiktok",
        "xhslink.com": "xiaohongshu",
        "www.xiaohongshu.com": "xiaohongshu",
        "v.kuaishou.com": "kuaishou",
        "v.m.chenzhongtech.com": "kuaishou",
        "m.gifshow.com": "kuaishou",
        "player.vimeo.com": "vimeo",
        "dailymotion.com": "dailymotion",
        "www.dailymotion.com": "dailymotion",
        "dai.ly": "dailymotion",
        "x.com": "x",
        "www.instagram.com": "instagram",
        "fb.watch": "facebook",
        "web.facebook.com": "facebook",
        "clips.twitch.tv": "twitch",
        "redd.it": "reddit",
        "pin.it": "pinterest",
        "m.weibo.cn": "weibo",
        "v.youku.com": "youku",
        "v.qq.com": "qqvideo",
        "weixin.qq.com": "wechat_channels",
        "www.snapchat.com": "snapchat",
        "www.linkedin.com": "linkedin",
        "t.me": "telegram",
        "kick.com": "kick",
        "www.tumblr.com": "tumblr",
    }

    assert {
        hostname: provider_profile(f"https://{hostname}/video/1").key
        for hostname in expected
    } == expected


def test_unknown_hosts_use_the_safe_generic_strategy() -> None:
    profile = provider_profile("https://media.example.com/video/1")

    assert profile.key == "generic"
    assert default_provider_registry().profile_for_key("generic") == profile
    assert profile.command_args == ()
    assert not hasattr(profile, "inspection_attempts")


def test_peertube_requires_an_exact_approved_instance_and_video_path() -> None:
    configure_provider_instances(frozenset({"video.example.com"}))
    try:
        url = "https://video.example.com/w/AbCdEfGhIjKlMnOpQrStUv"
        profile = provider_profile(url)

        assert profile.key == "peertube"
        assert profile.version == "peertube-approved-instance"
        assert provider_request_url(url) == url
        assert (
            provider_profile(
                "https://unapproved.example.com/w/AbCdEfGhIjKlMnOpQrStUv"
            ).key
            == "generic"
        )
        with pytest.raises(RunnerFailure) as captured:
            provider_request_url("https://video.example.com/videos/recently-added")
        assert captured.value.code == "provider_unsupported"
    finally:
        configure_provider_instances(frozenset())


def test_identity_declarations_are_the_rebuild_design():
    from app.services.provider_types import ProviderIdentity

    registry = default_provider_registry()
    required = {
        p.key for p in registry.profiles if p.identity is ProviderIdentity.REQUIRED
    }
    assert required == {"wechat_channels", "qqvideo", "youku", "instagram"}
    assert registry.profile_for_key("bilibili").identity is ProviderIdentity.PREFER
    assert registry.profile_for_key("reddit").identity is ProviderIdentity.PREFER
    assert registry.profile_for_key("tiktok").identity is ProviderIdentity.NONE


def test_registry_declares_content_scope_for_all_profiles():
    from app.workers.runner.provider_registry import default_provider_registry

    for profile in default_provider_registry().profiles:
        assert profile.content_scope == (
            "personal_full" if profile.key in {"qqvideo", "youku"} else "public"
        )
    assert (
        provider_profile("https://media.example.com/file.mp4").content_scope == "public"
    )


def test_registry_rejects_invalid_content_scope():
    from dataclasses import replace

    from app.workers.runner.provider_registry import ProviderRegistry

    with pytest.raises(ValueError, match="content scope"):
        ProviderRegistry(
            [
                replace(
                    provider_profile("https://www.youtube.com/watch?v=x"),
                    content_scope="unsafe",
                )
            ]
        )


def test_article_registry_has_no_direct_video_capability() -> None:
    profile = provider_profile("https://mp.weixin.qq.com/s/article-share")
    assert profile.key == ProviderKey.WECHAT_OFFICIAL_ACCOUNT_ARTICLE
    assert profile.capabilities == frozenset()
    ProviderRegistry((profile,))
    with pytest.raises(ValueError, match="incomplete capabilities"):
        ProviderRegistry(
            (
                ProviderProfile(
                    "empty",
                    "Empty",
                    frozenset({"empty.example"}),
                    capabilities=frozenset(),
                ),
            )
        )


def test_hongguo_public_web_share_does_not_request_account_cookies() -> None:
    from app.services.provider_types import ProviderIdentity

    profile = provider_profile(
        "https://hongguoduanju.com/player/7662704510720019480/7662705589293681726"
    )
    assert profile.content_scope == "public"
    assert profile.identity is ProviderIdentity.NONE
    assert not profile.cookie_domain_allowlist


def test_channels_declares_page_identity_without_claiming_parser_availability() -> None:
    from app.services.provider_types import Layer
    from app.workers.identity.yuanbao_parse import YUANBAO_ORIGIN
    from app.workers.runner.engine.layers.browser import BrowserLayer

    profile = provider_profile("https://weixin.qq.com/sph/A9znfitafp")
    assert profile.identity_source == "yuanbao_native"
    assert profile.identity_origin == YUANBAO_ORIGIN
    assert not profile.cookie_domain_allowlist
    assert profile.content_scope == "public"
    assert profile.support_status is ProviderSupportStatus.UNKNOWN
    assert profile.ladder == (Layer.L3,)
    assert not BrowserLayer.has_parser(profile.key)


@pytest.mark.parametrize(
    "change",
    [
        {"key": "instagram"},
        {"identity_origin": "https://other.invalid"},
        {"identity_origin": None},
        {"cookie_domain_allowlist": frozenset({"yuanbao.tencent.com"})},
        {"content_scope": "personal_full"},
    ],
)
def test_page_identity_cannot_expand_source_or_content_scope(change) -> None:
    profile = provider_profile("https://weixin.qq.com/sph/A9znfitafp")
    if "key" in change:
        assert profile.l3_rules is not None
        change = {
            **change,
            "l3_rules": replace(profile.l3_rules, platform=change["key"]),
        }
    with pytest.raises(ValueError, match="invalid page identity"):
        ProviderRegistry((replace(profile, **change),))


def test_cookie_profile_rejects_page_origin_declaration() -> None:
    from app.workers.identity.yuanbao_parse import YUANBAO_ORIGIN

    profile = provider_profile("https://www.instagram.com/p/example/")
    assert profile.identity_source == "cookies" and profile.identity_origin is None
    with pytest.raises(ValueError, match="invalid identity origin"):
        ProviderRegistry((replace(profile, identity_origin=YUANBAO_ORIGIN),))
