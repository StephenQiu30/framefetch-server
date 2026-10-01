"""Built-in profiles and Design 17's initial engine declarations."""

from dataclasses import replace
from urllib.parse import SplitResult

from app.services.provider_types import BrowserRules, EgressRoute, Layer, PrepareSpec
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_catalog_core import CORE_PROVIDER_PROFILES
from app.workers.runner.provider_catalog_public import PUBLIC_PROVIDER_PROFILES
from app.workers.runner.provider_catalog_social import SOCIAL_PROVIDER_PROFILES
from app.workers.runner.provider_registry import ProviderProfile

_CN = frozenset(
    {
        "bilibili",
        "douyin",
        "xiaohongshu",
        "kuaishou",
        "weibo",
        "wechat_channels",
        "qqvideo",
        "youku",
        "hongguo_web",
        "wechat_official_account_article",
    }
)
_LADDERS = {
    "youtube": (Layer.L2, Layer.L3),
    "douyin": (Layer.L3, Layer.L1),
    "tiktok": (Layer.L1, Layer.L3),
    "xiaohongshu": (Layer.L3, Layer.L1),
    "kuaishou": (Layer.L2, Layer.L3),
    "weibo": (Layer.L2, Layer.L3),
    "wechat_channels": (Layer.L3,),
    "qqvideo": (Layer.L1, Layer.L3),
    "youku": (Layer.L1, Layer.L3),
    "hongguo_web": (Layer.L1, Layer.L3),
    "x": (Layer.L1, Layer.L3),
    "instagram": (Layer.L1, Layer.L3),
    "facebook": (Layer.L1, Layer.L3),
}
_PREPARE = {
    "youtube": PrepareSpec("po_token", ("mweb", "tv", "default")),
    "kuaishou": PrepareSpec("visitor"),
    "weibo": PrepareSpec("visitor"),
}


def _engine_profile(profile: ProviderProfile) -> ProviderProfile:
    ladder = _LADDERS.get(profile.key, (Layer.L1,))
    return replace(
        profile,
        ladder=ladder,
        egress_route=EgressRoute.CN if profile.key in _CN else EgressRoute.GLOBAL,
        l2_prepare=_PREPARE.get(profile.key),
        l3_rules=BrowserRules(profile.key) if Layer.L3 in ladder else None,
    )


def _article_url(url: str, parsed: SplitResult) -> str:
    if not parsed.path.startswith("/s/") or parsed.path == "/s/":
        raise RunnerFailure("provider_unsupported", status=422)
    return url


_ARTICLE = ProviderProfile(
    key="wechat_official_account_article",
    display_name="微信公众号文章",
    hosts=frozenset({"mp.weixin.qq.com"}),
    normalize_url=_article_url,
)


# Remaining public single-video platforms and approved PeerTube use global L1.
DEFAULT_PROVIDER_PROFILES: tuple[ProviderProfile, ...] = tuple(
    _engine_profile(profile)
    for profile in (
        *CORE_PROVIDER_PROFILES,
        *SOCIAL_PROVIDER_PROFILES,
        *PUBLIC_PROVIDER_PROFILES,
        _ARTICLE,
    )
)
