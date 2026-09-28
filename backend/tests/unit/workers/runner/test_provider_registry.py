import pytest
from app.services.provider_types import (
    ProviderAccessMode,
    ProviderCapability,
    ProviderKey,
    ProviderProfileVersion,
    ProviderSupportStatus,
)
from app.services.site_sessions import known_session_provider_keys
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


def provider_inspection_attempts(url: str) -> int:
    return provider_request(url).profile.inspection_attempts


def provider_inspection_retry_delay(url: str) -> float:
    return provider_request(url).profile.inspection_retry_delay


def test_uses_public_vimeo_player_endpoint_for_canonical_video() -> None:
    assert (
        provider_request_url("https://vimeo.com/76979871?share=copy")
        == "https://player.vimeo.com/video/76979871"
    )
    assert (
        provider_request_url("https://www.vimeo.com/76979871/")
        == "https://player.vimeo.com/video/76979871"
    )


def test_youtube_uses_the_managed_mweb_pot_route() -> None:
    profile = provider_profile("https://www.youtube.com/watch?v=owned")

    assert profile.version == ProviderProfileVersion.YOUTUBE
    assert profile.client_profile_id == "youtube-mweb"
    assert profile.attestation_policy == "bgutil-mweb-player-gvs"
    assert profile.yt_dlp_retry_count == 0
    assert profile.inspection_attempts == 1


def test_builtin_profiles_use_centralized_provider_identifiers() -> None:
    profiles = ProviderRegistry(default_provider_registry().profiles).profiles

    provider_keys = {key.value for key in ProviderKey}
    profile_versions = {version.value for version in ProviderProfileVersion}

    assert all(profile.key in provider_keys for profile in profiles)
    assert all(profile.version in profile_versions for profile in profiles)


def test_operator_profiles_and_site_session_policies_are_the_same_set() -> None:
    operator_profiles = {
        profile.key
        for profile in default_provider_registry().profiles
        if ProviderAccessMode.OPERATOR_MANAGED in profile.access_modes
    }

    assert operator_profiles == known_session_provider_keys()


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
    assert provider_profile(url).support_status is ProviderSupportStatus.VERIFIED


def test_hongguo_official_share_is_a_single_video_profile() -> None:
    profile = provider_profile("https://novelquickapp.com/s/YMc-jWnOo1U/")

    assert profile.key == "hongguo_web"
    assert profile.version == "hongguo-official-share"
    assert profile.support_status is ProviderSupportStatus.VERIFIED
    assert profile.capabilities == frozenset({ProviderCapability.SINGLE_VIDEO})


def test_qqvideo_supports_anonymous_and_optional_operator() -> None:
    url = "https://v.qq.com/x/page/q326831cny0.html"
    profile = provider_profile(url)
    assert profile.support_status is ProviderSupportStatus.UNKNOWN
    assert profile.access_modes == (
        ProviderAccessMode.ANONYMOUS,
        ProviderAccessMode.OPERATOR_MANAGED,
    )
    assert provider_request_url(url) == url
    assert profile.probe_authenticated_media is True
    assert profile.command_args == (
        "--socket-timeout",
        "10",
        "--concurrent-fragments",
        "4",
    )


def test_preserves_unlisted_and_non_vimeo_urls() -> None:
    assert (
        provider_request_url("https://vimeo.com/76979871/private-hash")
        == "https://vimeo.com/76979871/private-hash"
    )


def test_remaining_provider_profiles_record_verified_access_boundaries() -> None:
    facebook = provider_profile("https://www.facebook.com/reel/1195289147628387")
    instagram = provider_profile("https://www.instagram.com/reel/DbKfjdhTMAY/")
    twitch = provider_profile("https://clips.twitch.tv/FaintLightGullWholeWheat")
    reddit = provider_profile("https://www.reddit.com/comments/124pp33")
    douyin = provider_profile("https://www.douyin.com/video/7647907920252949425")
    tiktok = provider_profile(
        "https://www.tiktok.com/@creator/video/6742501081818877190"
    )
    wechat = provider_profile("https://weixin.qq.com/sph/AFWYoXF5Bw")

    assert facebook.version == "facebook-public-reel"
    assert facebook.client_profile_id == "chrome-136-macos-15"
    assert ProviderCapability.SHORT_VIDEO in facebook.capabilities
    assert facebook.probe_authenticated_media is True
    assert instagram.probe_authenticated_media is True
    assert twitch.version == "twitch-public-clip"
    assert twitch.capabilities == frozenset(
        {
            ProviderCapability.SINGLE_VIDEO,
            ProviderCapability.CLIP_OR_VOD,
        }
    )
    assert reddit.support_status is ProviderSupportStatus.ACCESS_REQUIRED
    assert reddit.version == "reddit-public-video"
    assert douyin.version == "douyin-public"
    assert douyin.support_status is ProviderSupportStatus.ACCESS_REQUIRED
    assert douyin.access_modes == (
        ProviderAccessMode.ANONYMOUS,
        ProviderAccessMode.OPERATOR_MANAGED,
        ProviderAccessMode.GUEST,
    )
    assert tiktok.support_status is ProviderSupportStatus.VERIFIED
    assert tiktok.version == "tiktok-public-player"
    assert wechat.version == "wechat-channels-public"
    assert wechat.support_status is ProviderSupportStatus.ACCESS_REQUIRED
    assert wechat.access_modes == (
        ProviderAccessMode.ANONYMOUS,
        ProviderAccessMode.OPERATOR_MANAGED,
    )
    assert wechat.cookie_domain_allowlist == frozenset({"yuanbao.tencent.com"})
    assert ProviderCapability.SHORT_VIDEO in wechat.capabilities
    assert wechat.probe_authenticated_media is True
    assert wechat.probe_media_duration is True


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
        url: (provider_profile(url).version, provider_profile(url).client_profile_id)
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


def test_tiktok_uses_anonymous_first_party_player_profile() -> None:
    url = "https://www.tiktok.com/@creator/video/123"
    profile = provider_profile(url)

    assert provider_command_args(url) == ()
    assert provider_inspection_attempts(url) == 2
    assert provider_inspection_retry_delay(url) == 1
    assert profile.access_modes == (ProviderAccessMode.ANONYMOUS,)
    assert profile.cookie_domain_allowlist == frozenset()
    assert profile.credential_concurrency == 0
    assert profile.client_profile_id == "yt-dlp-default"
    assert profile.canary_suite == "tiktok-public-player-video"
    assert provider_command_args("https://vimeo.com/123") == ("--check-formats",)
    assert provider_inspection_attempts("https://vimeo.com/123") == 2
    assert provider_inspection_retry_delay("https://vimeo.com/123") == 1


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


def test_targets_douyin_request_impersonation_and_retries() -> None:
    url = "https://www.douyin.com/video/123"

    assert provider_command_args(url) == (
        "--impersonate",
        "Chrome-136:Macos-15",
    )
    assert provider_inspection_attempts(url) == 8
    assert provider_inspection_retry_delay(url) == 0.5
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
    assert provider_inspection_attempts(short_url) == 8


def test_targets_xiaohongshu_short_links_with_browser_impersonation() -> None:
    for url in (
        "https://xhslink.com/m/AbC123",
        "https://www.xiaohongshu.com/explore/abc123",
    ):
        assert provider_command_args(url) == (
            "--impersonate",
            "Chrome-136:Macos-15",
        )
        assert provider_inspection_attempts(url) == 8
        assert provider_inspection_retry_delay(url) == 0.5
        assert provider_profile(url).support_status is ProviderSupportStatus.DEGRADED
        assert provider_profile(url).cookie_domain_allowlist == frozenset(
            {"xiaohongshu.com"}
        )


def test_tumblr_uses_bounded_rate_limit_backoff() -> None:
    url = (
        "https://www.tumblr.com/maskofthedragon/"
        "626907179849564160/mona-talking-in-english"
    )

    assert provider_inspection_attempts(url) == 4
    assert provider_inspection_retry_delay(url) == 4


def test_slow_public_extractors_use_bounded_retry_backoff() -> None:
    telegram = "https://t.me/europa_press/613"
    kick = "https://kick.com/spreen/clips/clip_01J8RGZRKHXHXXKJEHGRM932A5"

    assert provider_inspection_attempts(telegram) == 4
    assert provider_inspection_retry_delay(telegram) == 4
    assert provider_inspection_attempts(kick) == 8
    assert provider_inspection_retry_delay(kick) == 4


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
    assert provider_inspection_attempts(url) == 4
    assert provider_inspection_retry_delay(url) == 0.5
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
    assert profile.inspection_attempts == 2


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
