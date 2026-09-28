"""Ordered, data-driven yt-dlp failure classification rules."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.downloads.rules.content_restrictions import ContentRestriction
from app.services.provider_types import ProviderKey


@dataclass(frozen=True, slots=True)
class ProviderFailureContext:
    provider_key: str
    source_url: str
    authenticated: bool


@dataclass(frozen=True, slots=True)
class FailureRule:
    code: str
    status: int
    any_stderr: tuple[bytes, ...] = ()
    all_stderr: tuple[bytes, ...] = ()
    providers: frozenset[str] = frozenset()
    any_url: tuple[str, ...] = ()
    authenticated: bool | None = None

    def matches(self, context: ProviderFailureContext, stderr: bytes) -> bool:
        source_url = context.source_url.casefold()
        return (
            (not self.providers or context.provider_key in self.providers)
            and (not self.any_url or any(value in source_url for value in self.any_url))
            and (
                self.authenticated is None
                or context.authenticated is self.authenticated
            )
            and (
                not self.any_stderr
                or any(marker in stderr for marker in self.any_stderr)
            )
            and all(marker in stderr for marker in self.all_stderr)
        )


PROVIDER_FAILURE_RULES: tuple[FailureRule, ...] = (
    *(
        FailureRule(
            code,
            status,
            any_stderr=(f"framefetch {code}".encode(),),
            providers=frozenset({ProviderKey.WEIBO}),
        )
        for code, status in (
            ("provider_link_unavailable", 422),
            ("provider_rate_limited", 429),
            ("provider_temporarily_unavailable", 503),
        )
    ),
    FailureRule(
        "credential_required",
        422,
        any_stderr=(b"framefetch credential_required",),
        providers=frozenset({ProviderKey.QQVIDEO}),
    ),
    *(
        FailureRule(
            reason.value,
            422,
            any_stderr=(f"framefetch {reason.value}".encode(),),
            providers=frozenset(
                {
                    ProviderKey.BILIBILI,
                    ProviderKey.DOUYIN,
                    ProviderKey.YOUKU,
                    ProviderKey.QQVIDEO,
                }
            ),
        )
        for reason in ContentRestriction
    ),
    FailureRule(
        "content_preview_only",
        422,
        any_stderr=(b"only the preview will be extracted",),
        providers=frozenset({ProviderKey.BILIBILI}),
    ),
    FailureRule(
        "content_supporter_only",
        422,
        any_stderr=(b"this is a supporter-only video",),
        providers=frozenset({ProviderKey.BILIBILI}),
    ),
    FailureRule(
        "pot_provider_unavailable",
        503,
        all_stderr=(b"error reaching get ", b"/ping", b"server is reachable"),
        providers=frozenset({ProviderKey.YOUTUBE}),
    ),
    FailureRule(
        "egress_challenged",
        422,
        any_stderr=(b"http error 412", b"precondition failed"),
        providers=frozenset({ProviderKey.BILIBILI}),
    ),
    FailureRule(
        "pot_provider_unavailable",
        503,
        all_stderr=(b"po token provider", b"server is not available"),
        providers=frozenset({ProviderKey.YOUTUBE}),
    ),
    FailureRule(
        "provider_unsupported",
        422,
        any_stderr=(b"unsupported url:",),
        any_url=("channels.weixin.qq.com",),
    ),
    FailureRule(
        "provider_unsupported",
        422,
        any_stderr=(b"kuaishou image posts are not supported by the video runner",),
        providers=frozenset({ProviderKey.KUAISHOU}),
    ),
    FailureRule(
        "provider_media_unsupported",
        422,
        any_stderr=(b"facebook post does not contain a downloadable video",),
        providers=frozenset({ProviderKey.FACEBOOK}),
    ),
    FailureRule(
        "provider_link_unavailable",
        422,
        any_stderr=(
            b"unsupported url:",
            b"kuaishou public link unavailable",
            b"xiaohongshu note unavailable",
        ),
        providers=frozenset(
            {ProviderKey.DOUYIN, ProviderKey.XIAOHONGSHU, ProviderKey.KUAISHOU}
        ),
    ),
    FailureRule(
        "provider_media_unsupported",
        422,
        any_stderr=(b"douyin official note is not a supported single video",),
        providers=frozenset({ProviderKey.DOUYIN}),
    ),
    FailureRule(
        "provider_link_unavailable",
        422,
        any_stderr=(b"douyin official share link unavailable",),
        providers=frozenset({ProviderKey.DOUYIN}),
    ),
    FailureRule(
        "provider_temporarily_unavailable",
        503,
        any_stderr=(b"douyin official share link temporarily unavailable",),
        providers=frozenset({ProviderKey.DOUYIN}),
    ),
    FailureRule(
        "extractor_regression",
        502,
        any_stderr=(b"douyin official share link response structure changed",),
        providers=frozenset({ProviderKey.DOUYIN}),
    ),
    FailureRule(
        "egress_challenged",
        422,
        any_stderr=(b"douyin official share link verification required",),
        providers=frozenset({ProviderKey.DOUYIN}),
    ),
    FailureRule(
        "provider_rate_limited",
        429,
        any_stderr=(b"douyin official share link rate limited",),
        providers=frozenset({ProviderKey.DOUYIN}),
    ),
    FailureRule(
        "provider_link_unavailable",
        422,
        any_stderr=(b"unable to extract initial state",),
        providers=frozenset({ProviderKey.XIAOHONGSHU, ProviderKey.KUAISHOU}),
    ),
    FailureRule(
        "provider_link_unavailable",
        422,
        any_stderr=(
            b"unsupported url:",
            b"tiktok video not available from the official player",
        ),
        providers=frozenset({ProviderKey.TIKTOK}),
    ),
    FailureRule(
        "extractor_regression",
        502,
        any_stderr=(b"tiktok official player response structure changed",),
        providers=frozenset({ProviderKey.TIKTOK}),
    ),
    FailureRule(
        "provider_link_unavailable",
        422,
        any_stderr=(b"domain not found",),
        providers=frozenset({ProviderKey.X}),
    ),
    FailureRule(
        "provider_link_unavailable",
        422,
        any_stderr=(b"wechat channels public link unavailable",),
        providers=frozenset({ProviderKey.WECHAT_CHANNELS}),
    ),
    FailureRule(
        "content_entitlement_unknown",
        422,
        any_stderr=(b"wechat channels public media is not downloadable",),
        providers=frozenset({ProviderKey.WECHAT_CHANNELS}),
    ),
    FailureRule(
        "drm_protected",
        422,
        any_stderr=(
            b"framefetch drm_protected",
            b"only drm protected formats",
            b"this video is drm protected",
            b"this format is drm protected",
        ),
    ),
    FailureRule(
        "content_private",
        403,
        any_stderr=(b"private video", b"this video is private"),
    ),
    FailureRule(
        "content_not_entitled",
        403,
        any_stderr=(
            b"members-only content",
            b"join this channel",
            b"premium-only",
            b"subscriber-only",
            b"not entitled",
        ),
    ),
    FailureRule(
        "credential_expired",
        422,
        any_stderr=(
            b"account cookies are no longer valid",
            b"cookies have been rotated",
            b"cookie is no longer valid",
        ),
    ),
    FailureRule(
        "egress_challenged",
        422,
        all_stderr=(b"sign in to confirm", b"not a bot"),
    ),
    FailureRule(
        "provider_geo_restricted",
        422,
        any_stderr=(
            b"not available in your country",
            b"not available in your region",
            b"geo restricted",
        ),
    ),
    FailureRule(
        "provider_geo_restricted",
        422,
        any_stderr=(b"your ip address is blocked from accessing this post",),
        providers=frozenset({ProviderKey.TIKTOK}),
    ),
    FailureRule(
        "egress_challenged",
        422,
        any_stderr=(b"xiaohongshu request verification required",),
        providers=frozenset({ProviderKey.XIAOHONGSHU}),
    ),
    FailureRule(
        "pot_provider_unavailable",
        503,
        any_stderr=(b"provider unavailable", b"provider failed", b"timed out"),
        all_stderr=(b"po token",),
    ),
    FailureRule(
        "pot_rejected",
        422,
        any_stderr=(b"invalid", b"rejected", b"http error 403"),
        all_stderr=(b"po token",),
    ),
    FailureRule(
        "pot_required",
        422,
        any_stderr=(b"required", b"was not provided", b"missing"),
        all_stderr=(b"po token",),
    ),
    FailureRule(
        "egress_challenged",
        422,
        any_stderr=(
            b"unable to download video data: http error 403",
            b"http error 403: forbidden",
        ),
        providers=frozenset({ProviderKey.YOUTUBE}),
        authenticated=False,
    ),
    FailureRule(
        "provider_temporarily_unavailable",
        503,
        any_stderr=(
            b"instagram api is not granting access",
            b"instagram sent an empty media response",
        ),
        providers=frozenset({ProviderKey.INSTAGRAM}),
        authenticated=False,
    ),
    FailureRule(
        "credential_expired",
        422,
        all_stderr=(b"fresh cookies", b"needed"),
        authenticated=True,
    ),
    FailureRule(
        "guest_context_required",
        503,
        all_stderr=(b"fresh cookies", b"needed"),
        providers=frozenset({ProviderKey.DOUYIN}),
        authenticated=False,
    ),
    FailureRule(
        "provider_temporarily_unavailable",
        503,
        all_stderr=(b"fresh cookies", b"needed"),
        providers=frozenset({ProviderKey.DOUYIN}),
    ),
    FailureRule(
        "provider_rate_limited",
        429,
        any_stderr=(b"http error 429", b"too many requests"),
        all_stderr=(b"rate-limit reached or login required",),
    ),
    FailureRule(
        "provider_temporarily_unavailable",
        503,
        any_stderr=(b"rate-limit reached or login required",),
    ),
    FailureRule(
        "format_unavailable",
        409,
        any_stderr=(b"no video formats found",),
        providers=frozenset({ProviderKey.INSTAGRAM}),
    ),
    # Only Douyin has a guest route (rule above); every other platform that
    # asks for cookies needs a deployment session an administrator logs in.
    FailureRule(
        "provider_session_not_ready",
        503,
        all_stderr=(b"fresh cookies", b"needed"),
        authenticated=False,
    ),
    FailureRule(
        "credential_required",
        422,
        any_stderr=(
            b"vimeo extractor only works when logged-in",
            b"account authentication is required",
            b"login required. use --cookies",
        ),
    ),
    FailureRule(
        "provider_rate_limited",
        429,
        any_stderr=(b"http error 429", b"too many requests", b"rate limit exceeded"),
    ),
    FailureRule(
        "provider_temporarily_unavailable",
        503,
        any_stderr=(b"tiktok official player api temporarily unavailable",),
        providers=frozenset({ProviderKey.TIKTOK}),
    ),
    FailureRule(
        "provider_link_unavailable",
        422,
        any_stderr=(
            b"video unavailable",
            b"this video is unavailable",
            b"video is no longer available",
        ),
        providers=frozenset({ProviderKey.YOUTUBE}),
    ),
    FailureRule(
        "extractor_regression",
        502,
        any_stderr=(
            b"cannot parse data",
            b"facebook post media structure could not be identified",
        ),
        providers=frozenset({ProviderKey.FACEBOOK}),
    ),
    FailureRule(
        "extractor_regression",
        502,
        any_stderr=(
            b"no video formats found",
            b"xiaohongshu note media structure could not be identified",
        ),
        providers=frozenset({ProviderKey.XIAOHONGSHU}),
    ),
    FailureRule(
        "extractor_regression",
        502,
        any_stderr=(
            b"unable to extract",
            b"expected one video in the playlist",
            b"unexpected response from webpage request",
            b"universal data for rehydration",
        ),
    ),
)


def classify_provider_failure(
    context: ProviderFailureContext,
    stderr: bytes,
) -> tuple[str, int] | None:
    normalized = stderr.lower()
    for rule in PROVIDER_FAILURE_RULES:
        if rule.matches(context, normalized):
            return rule.code, rule.status
    return None
