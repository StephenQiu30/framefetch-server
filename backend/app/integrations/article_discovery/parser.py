"""Bounded static HTML parser for public WeChat articles."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import replace
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from app.integrations.article_discovery.native_video import native_videos
from app.services.provider_types import ProviderKey
from app.services.source_discoveries.models import (
    ArticleDiscoveryCandidate,
    ArticleDiscoveryResult,
)
from app.services.source_discoveries.ports import (
    ArticleAccessRestricted,
    ArticleDiscoveryFailure,
)
from app.services.source_discovery import (
    DiscoveryDecisionHint,
    DiscoveryItemKind,
    DiscoveryItemStatus,
)

_MPVID = re.compile(r"wxv_[A-Za-z0-9_-]{4,128}")
_QQVIDEO_PATHS = (
    re.compile(r"/x/page/([A-Za-z0-9_-]{4,64})\.html"),
    re.compile(r"/x/cover/[A-Za-z0-9_-]{4,128}/([A-Za-z0-9_-]{4,64})\.html"),
)
_CHANNELS_PATH = re.compile(r"/sph/[A-Za-z0-9_-]{4,256}/?")
_RESTRICTED_MARKERS = (
    "环境异常",
    "访问过于频繁",
    "安全验证",
    "请输入验证码",
    "该内容为付费内容",
    "登录后继续",
)


class _ArticleHtmlParser(HTMLParser):
    def __init__(self, *, max_items: int) -> None:
        super().__init__(convert_charrefs=True)
        self.max_items = max_items
        self.title = ""
        self._in_title = False
        self._in_activity_title = False
        self.has_article_body = False
        self.embeds: list[tuple[str, dict[str, str]]] = []
        self._tags: list[str] = []
        self._visible_text: list[str] = []
        self._page_notices: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        tag = tag.casefold()
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self._tags.append(tag)
        if tag == "title":
            self._in_title = True
        if values.get("id") == "activity-name":
            self._in_activity_title = True
        if values.get("id") == "js_content":
            self.has_article_body = True
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").casefold()
            if key in {"og:title", "twitter:title"} and values.get("content"):
                self.title = values["content"]
        if tag in {"iframe", "mpvideo", "mp-common-videosnap", "video"}:
            if len(self.embeds) >= self.max_items:
                raise ArticleDiscoveryFailure("article embed limit exceeded")
            self.embeds.append((tag, values))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self._tags:
            index = len(self._tags) - 1 - self._tags[::-1].index(tag)
            del self._tags[index:]
        if tag.casefold() == "title":
            self._in_title = False
        if tag.casefold() == "h1":
            self._in_activity_title = False

    def handle_data(self, data: str) -> None:
        if any(tag in {"script", "style", "template"} for tag in self._tags):
            return
        self._visible_text.append(data)
        if not self._tags or self._tags[-1] in {"html", "body"}:
            self._page_notices.append(data)
        if (self._in_title or self._in_activity_title) and not self.title:
            self.title = data

    def access_restricted(self) -> bool:
        # Text in article paragraphs and scripts is not a platform access signal.
        visible = " ".join(self._visible_text)
        if not self.has_article_body:
            return any(marker in visible for marker in _RESTRICTED_MARKERS)
        for text in self._page_notices:
            notice = text.strip()
            if notice in _RESTRICTED_MARKERS:
                return True
            if notice.endswith("环境异常，请完成验证后继续访问"):
                return True
        return False


def parse_article_html(
    payload: str,
    *,
    max_items: int = 24,
) -> ArticleDiscoveryResult:
    if not payload.strip():
        raise ArticleDiscoveryFailure("article HTML is empty")
    parser = _ArticleHtmlParser(max_items=max_items)
    try:
        parser.feed(payload)
        parser.close()
    except (ValueError, ArticleDiscoveryFailure) as exc:
        raise ArticleDiscoveryFailure("article HTML is invalid") from exc
    if parser.access_restricted():
        raise ArticleAccessRestricted("article access is restricted")
    if not parser.has_article_body:
        raise ArticleDiscoveryFailure("article body is unavailable")

    candidates: list[ArticleDiscoveryCandidate] = []
    seen: set[str] = set()
    for tag, attrs in parser.embeds:
        try:
            candidate = _classify_embed(tag, attrs)
        except ValueError as exc:
            raise ArticleDiscoveryFailure("article embed URL is invalid") from exc
        if candidate.identity_evidence_hash in seen:
            continue
        seen.add(candidate.identity_evidence_hash)
        candidates.append(candidate)
    for video in native_videos(payload, max_items=max_items):
        candidate = _candidate(
            DiscoveryItemKind.OFFICIAL_ACCOUNT_NATIVE,
            ProviderKey.WECHAT_OFFICIAL_ACCOUNT_ARTICLE,
            parser.title or "公众号原生视频",
            f"native:{video.video_id}",
            DiscoveryDecisionHint.CANDIDATE,
            DiscoveryItemStatus.READY,
        )
        candidate = replace(candidate, duration_ms=video.duration_ms)
        if candidate.identity_evidence_hash in seen:
            candidates = [
                candidate
                if item.identity_evidence_hash == candidate.identity_evidence_hash
                else item
                for item in candidates
            ]
        else:
            seen.add(candidate.identity_evidence_hash)
            candidates.append(candidate)
        if len(candidates) > max_items:
            raise ArticleDiscoveryFailure("article embed limit exceeded")
    return ArticleDiscoveryResult(
        title=_sanitize(parser.title) or "微信公众号文章",
        items=tuple(candidates),
    )


def _classify_embed(
    tag: str,
    attrs: dict[str, str],
) -> ArticleDiscoveryCandidate:
    mpvid = attrs.get("data-mpvid") or attrs.get("mpvid") or attrs.get("vid") or ""
    if _MPVID.fullmatch(mpvid):
        return _candidate(
            DiscoveryItemKind.OFFICIAL_ACCOUNT_NATIVE,
            ProviderKey.WECHAT_OFFICIAL_ACCOUNT_ARTICLE,
            attrs.get("data-title") or attrs.get("title") or "公众号原生视频",
            f"native:{mpvid}",
            DiscoveryDecisionHint.UNSUPPORTED,
            DiscoveryItemStatus.IDENTITY_UNVERIFIED,
        )

    src = html.unescape(attrs.get("src") or attrs.get("data-src") or "").strip()
    parsed = urlsplit(src)
    host = (parsed.hostname or "").casefold()
    if host == "v.qq.com":
        media_id = next(
            (
                match.group(1)
                for pattern in _QQVIDEO_PATHS
                if (match := pattern.fullmatch(parsed.path)) is not None
            ),
            None,
        )
        if media_id is None and parsed.path in {
            "/iframe/preview.html",
            "/txp/iframe/player.html",
        }:
            query = parse_qs(parsed.query, keep_blank_values=True)
            values = query.get("vid", [])
            if len(values) == 1 and re.fullmatch(r"[A-Za-z0-9_-]{4,64}", values[0]):
                media_id = values[0]
        if media_id is not None:
            return _candidate(
                DiscoveryItemKind.TENCENT_VIDEO,
                ProviderKey.QQVIDEO,
                attrs.get("title") or "腾讯视频",
                f"qqvideo:{media_id}",
                DiscoveryDecisionHint.CANDIDATE,
                DiscoveryItemStatus.READY,
                source_url=f"https://v.qq.com/x/page/{media_id}.html",
            )
    if tag == "mp-common-videosnap" or (
        host == "weixin.qq.com" and _CHANNELS_PATH.fullmatch(parsed.path)
    ):
        share = (
            f"https://weixin.qq.com{parsed.path.rstrip('/')}"
            if host == "weixin.qq.com"
            and _CHANNELS_PATH.fullmatch(parsed.path)
            and parsed.scheme in {"", "https"}
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
            else None
        )
        identity = (
            share or attrs.get("data-id") or attrs.get("id") or parsed.path or tag
        )
        return _candidate(
            DiscoveryItemKind.WECHAT_CHANNELS,
            ProviderKey.WECHAT_CHANNELS,
            attrs.get("data-title") or attrs.get("title") or "微信视频号内容",
            f"channels:{identity}",
            DiscoveryDecisionHint.CANDIDATE
            if share
            else DiscoveryDecisionHint.EXPORT_REQUIRED,
            DiscoveryItemStatus.READY,
            source_url=share,
        )
    evidence = f"unknown:{tag}:{src[:512]}:{attrs.get('id', '')}"
    return _candidate(
        DiscoveryItemKind.UNKNOWN,
        None,
        attrs.get("title") or "未知嵌入视频",
        evidence,
        DiscoveryDecisionHint.UNSUPPORTED,
        DiscoveryItemStatus.IDENTITY_UNVERIFIED,
    )


def _candidate(
    kind: DiscoveryItemKind,
    child_provider: str | None,
    title: str,
    evidence: str,
    hint: DiscoveryDecisionHint,
    status: DiscoveryItemStatus,
    *,
    source_url: str | None = None,
) -> ArticleDiscoveryCandidate:
    return ArticleDiscoveryCandidate(
        kind=kind,
        child_provider=child_provider,
        title=_sanitize(title) or "文章视频",
        duration_ms=None,
        identity_evidence_hash=hashlib.sha256(evidence.encode()).hexdigest(),
        decision_hint=hint,
        status=status,
        source_url=source_url,
    )


def _sanitize(value: str) -> str:
    return " ".join(html.unescape(value).split()).strip()[:200]
