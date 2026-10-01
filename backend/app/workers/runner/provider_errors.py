"""Ordered, data-driven yt-dlp failure classification rules."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.downloads.rules.content_restrictions import ContentRestriction
from app.services.provider_failures import failure_definition
from app.services.provider_types import ProviderKey


@dataclass(frozen=True, slots=True)
class ProviderFailureContext:
    provider_key: str
    source_url: str
    authenticated: bool
    egress_class: str = "unknown"


@dataclass(frozen=True, slots=True)
class FailureRule:
    code: str
    status: int
    any_stderr: tuple[bytes, ...] = ()
    all_stderr: tuple[bytes, ...] = ()
    providers: frozenset[str] = frozenset()
    any_url: tuple[str, ...] = ()
    authenticated: bool | None = None
    clear_media_overrides: bool = False

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
    FailureRule(
        "content_unavailable",
        422,
        any_stderr=(b"this video has been removed", b"this video has been deleted"),
    ),
    *(
        FailureRule(
            {
                "provider_link_unavailable": "content_unavailable",
                "provider_rate_limited": "rate_limited",
                "provider_temporarily_unavailable": "transient",
            }[code],
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
        "login_required",
        422,
        any_stderr=(b"framefetch login_required",),
        providers=frozenset(
            {ProviderKey.QQVIDEO, ProviderKey.YOUKU, ProviderKey.WECHAT_CHANNELS}
        ),
    ),
    *(
        FailureRule(
            "content_protected",
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
        "content_protected",
        422,
        any_stderr=(b"only the preview will be extracted",),
        providers=frozenset({ProviderKey.BILIBILI}),
    ),
    FailureRule(
        "content_protected",
        422,
        any_stderr=(b"this is a supporter-only video",),
        providers=frozenset({ProviderKey.BILIBILI}),
    ),
    FailureRule(
        "content_protected",
        422,
        any_stderr=(b"this video is protected by a password",),
        providers=frozenset({ProviderKey.VIMEO}),
    ),
    FailureRule(
        "content_unavailable",
        403,
        any_stderr=(
            b"because of its privacy settings, this video cannot be played here",
            b"cannot download embed-only video without embedding url",
        ),
        providers=frozenset({ProviderKey.VIMEO}),
    ),
    FailureRule(
        "runtime_unavailable",
        503,
        all_stderr=(b"error reaching get ", b"/ping", b"server is reachable"),
        providers=frozenset({ProviderKey.YOUTUBE}),
    ),
    FailureRule(
        "challenge",
        422,
        any_stderr=(b"http error 412", b"precondition failed"),
        providers=frozenset({ProviderKey.BILIBILI}),
    ),
    FailureRule(
        "runtime_unavailable",
        503,
        all_stderr=(b"po token provider", b"server is not available"),
        providers=frozenset({ProviderKey.YOUTUBE}),
    ),
    FailureRule(
        "invalid_input",
        422,
        any_stderr=(b"unsupported url:",),
        any_url=("channels.weixin.qq.com",),
    ),
    FailureRule(
        "invalid_input",
        422,
        any_stderr=(b"kuaishou image posts are not supported by the video runner",),
        providers=frozenset({ProviderKey.KUAISHOU}),
    ),
    FailureRule(
        "invalid_input",
        422,
        any_stderr=(b"facebook post does not contain a downloadable video",),
        providers=frozenset({ProviderKey.FACEBOOK}),
    ),
    FailureRule(
        "content_unavailable",
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
        "invalid_input",
        422,
        any_stderr=(b"douyin official note is not a supported single video",),
        providers=frozenset({ProviderKey.DOUYIN}),
    ),
    FailureRule(
        "content_unavailable",
        422,
        any_stderr=(b"douyin official share link unavailable",),
        providers=frozenset({ProviderKey.DOUYIN}),
    ),
    FailureRule(
        "transient",
        503,
        any_stderr=(b"douyin official share link temporarily unavailable",),
        providers=frozenset({ProviderKey.DOUYIN}),
    ),
    FailureRule(
        "extractor_broken",
        502,
        any_stderr=(b"douyin official share link response structure changed",),
        providers=frozenset({ProviderKey.DOUYIN}),
    ),
    FailureRule(
        "challenge",
        422,
        any_stderr=(b"douyin official share link verification required",),
        providers=frozenset({ProviderKey.DOUYIN}),
    ),
    FailureRule(
        "rate_limited",
        429,
        any_stderr=(b"douyin official share link rate limited",),
        providers=frozenset({ProviderKey.DOUYIN}),
    ),
    FailureRule(
        "extractor_broken",
        422,
        any_stderr=(b"unable to extract initial state",),
        providers=frozenset({ProviderKey.XIAOHONGSHU, ProviderKey.KUAISHOU}),
    ),
    FailureRule(
        "content_unavailable",
        422,
        any_stderr=(
            b"unsupported url:",
            b"tiktok video not available from the official player",
        ),
        providers=frozenset({ProviderKey.TIKTOK}),
    ),
    FailureRule(
        "extractor_broken",
        502,
        any_stderr=(b"tiktok official player response structure changed",),
        providers=frozenset({ProviderKey.TIKTOK}),
    ),
    FailureRule(
        "content_unavailable",
        422,
        any_stderr=(b"domain not found",),
        providers=frozenset({ProviderKey.X}),
    ),
    FailureRule(
        "content_unavailable",
        422,
        any_stderr=(b"wechat channels public link unavailable",),
        providers=frozenset({ProviderKey.WECHAT_CHANNELS}),
    ),
    FailureRule(
        "content_unavailable",
        422,
        any_stderr=(b"wechat channels public media is not downloadable",),
        providers=frozenset({ProviderKey.WECHAT_CHANNELS}),
    ),
    FailureRule(
        "content_protected",
        422,
        any_stderr=(
            b"framefetch drm_protected",
            b"only drm protected formats",
            b"this video is drm protected",
            b"this format is drm protected",
        ),
        clear_media_overrides=True,
    ),
    FailureRule(
        "content_unavailable",
        403,
        any_stderr=(b"private video", b"this video is private"),
    ),
    FailureRule(
        "content_unavailable",
        403,
        # YouTube returns localized playability reasons on the current JP exit.
        # This explicit private-content signal takes precedence over login hints.
        any_stderr=("非公開動画".encode(),),
        providers=frozenset({ProviderKey.YOUTUBE}),
    ),
    FailureRule(
        "content_unavailable",
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
        "login_required",
        422,
        any_stderr=(
            b"account cookies are no longer valid",
            b"cookies have been rotated",
            b"cookie is no longer valid",
        ),
    ),
    FailureRule(
        "network_blocked",
        422,
        all_stderr=(b"sign in to confirm", b"not a bot"),
    ),
    FailureRule(
        "network_blocked",
        422,
        any_stderr=(
            b"not available in your country",
            b"not available in your region",
            b"geo restricted",
        ),
    ),
    FailureRule(
        "network_blocked",
        422,
        any_stderr=(b"your ip address is blocked from accessing this post",),
        providers=frozenset({ProviderKey.TIKTOK}),
    ),
    FailureRule(
        "challenge",
        422,
        any_stderr=(b"xiaohongshu request verification required",),
        providers=frozenset({ProviderKey.XIAOHONGSHU}),
    ),
    FailureRule(
        "runtime_unavailable",
        503,
        any_stderr=(b"provider unavailable", b"provider failed", b"timed out"),
        all_stderr=(b"po token",),
    ),
    FailureRule(
        "challenge",
        422,
        any_stderr=(b"invalid", b"rejected", b"http error 403"),
        all_stderr=(b"po token",),
    ),
    FailureRule(
        "challenge",
        422,
        any_stderr=(b"required", b"was not provided", b"missing"),
        all_stderr=(b"po token",),
    ),
    FailureRule(
        "transient",
        503,
        any_stderr=(
            b"instagram api is not granting access",
            b"instagram sent an empty media response",
        ),
        providers=frozenset({ProviderKey.INSTAGRAM}),
        authenticated=False,
    ),
    FailureRule(
        "challenge",
        502,
        all_stderr=(b"fresh cookies", b"needed"),
    ),
    FailureRule(
        "rate_limited",
        429,
        any_stderr=(b"http error 429", b"too many requests"),
        all_stderr=(b"rate-limit reached or login required",),
    ),
    FailureRule(
        "extractor_broken",
        502,
        any_stderr=(b"rate-limit reached or login required",),
    ),
    FailureRule(
        "format_unavailable",
        409,
        any_stderr=(b"no video formats found",),
        providers=frozenset({ProviderKey.INSTAGRAM}),
    ),
    FailureRule(
        "login_required",
        422,
        any_stderr=(
            b"vimeo extractor only works when logged-in",
            b"account authentication is required",
            b"login required. use --cookies",
            b"sign in to confirm your age",
            b"this video requires login",
        ),
    ),
    FailureRule(
        "rate_limited",
        429,
        any_stderr=(b"http error 429", b"too many requests", b"rate limit exceeded"),
    ),
    FailureRule(
        "transient",
        503,
        any_stderr=(b"tiktok official player api temporarily unavailable",),
        providers=frozenset({ProviderKey.TIKTOK}),
    ),
    FailureRule(
        "extractor_broken",
        502,
        any_stderr=(
            b"video unavailable",
            b"this video is unavailable",
            b"video is no longer available",
        ),
        providers=frozenset({ProviderKey.YOUTUBE}),
    ),
    FailureRule(
        "extractor_broken",
        502,
        any_stderr=(
            b"cannot parse data",
            b"facebook post media structure could not be identified",
        ),
        providers=frozenset({ProviderKey.FACEBOOK}),
    ),
    FailureRule(
        "extractor_broken",
        502,
        any_stderr=(
            b"no video formats found",
            b"xiaohongshu note media structure could not be identified",
        ),
        providers=frozenset({ProviderKey.XIAOHONGSHU}),
    ),
    FailureRule(
        "extractor_broken",
        502,
        any_stderr=(
            b"unable to extract",
            b"expected one video in the playlist",
            b"unexpected response from webpage request",
            b"universal data for rehydration",
        ),
    ),
    FailureRule(
        "network_blocked",
        502,
        any_stderr=(
            b"http error 407",
            b"proxy authentication required",
            b"tunnel connection failed",
            b"proxy connection refused",
        ),
    ),
    FailureRule(
        "transient",
        503,
        any_stderr=(
            b"connection timed out",
            b"read timed out",
            b"connection reset",
            b"name or service not known",
            b"temporary failure in name resolution",
            b"certificate verify failed",
            b"ssl handshake",
            b"failed to resolve",
            b"network is unreachable",
            b"http error 500",
            b"http error 502",
            b"http error 503",
            b"http error 504",
        ),
    ),
    FailureRule(
        "runtime_unavailable",
        503,
        any_stderr=(b"no supported javascript runtime could be found",),
    ),
    FailureRule(
        "format_unavailable",
        422,
        any_stderr=(b"unsupported protocol", b"sabr is not supported", b"sabr-only"),
    ),
    FailureRule(
        "extractor_broken",
        502,
        any_stderr=(
            b"failed to parse json",
            b"empty response",
            b"no json object could be decoded",
        ),
    ),
    FailureRule("network_blocked", 502, any_stderr=(b"http error 403",)),
)


def _rule_priority(rule: FailureRule) -> int:
    return {
        "content_protected": 0,
        "content_unavailable": 0,
        "invalid_input": 0,
        "rate_limited": 1,
        "login_required": 3,
        "challenge": 4,
        "network_blocked": 5,
        "runtime_unavailable": 2,
        "transient": 5,
        "extractor_broken": 6,
        "format_unavailable": 7,
    }.get(rule.code, 5)


def classify_provider_failure(
    context: ProviderFailureContext,
    stderr: bytes,
    *,
    has_clear_media: bool = False,
) -> tuple[str, int] | None:
    normalized = stderr.lower()
    matched = [
        rule
        for rule in PROVIDER_FAILURE_RULES
        if rule.matches(context, normalized)
        and not (has_clear_media and rule.clear_media_overrides)
    ]
    if (
        context.provider_key == ProviderKey.YOUTUBE
        and context.egress_class == "datacenter"
        and b"login_required" in normalized
    ):
        matched.append(FailureRule("network_blocked", 422))
    candidates = matched
    if not candidates:
        return None
    rule = min(candidates, key=_rule_priority)
    return failure_definition(rule.code)[0].value, rule.status
