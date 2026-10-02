from __future__ import annotations

import httpx
import pytest
from app.integrations.article_discovery.adapter import WeChatArticleDiscoveryAdapter
from app.integrations.article_discovery.parser import parse_article_html
from app.services.source_discoveries.ports import (
    ArticleAccessRestricted,
    ArticleDiscoveryFailure,
)
from app.services.source_discovery import (
    DiscoveryDecisionHint,
    DiscoveryItemKind,
    DiscoveryItemStatus,
)

ARTICLE_URL = "https://mp.weixin.qq.com/s/article_123"


def test_static_parser_classifies_embeds_in_dom_order_without_leaking_urls() -> None:
    signed_url = "https://mpvideo.qpic.cn/path/native.mp4?token=secret"
    payload = f"""
    <html>
      <head><meta property="og:title" content="  安全文章  "></head>
      <body id="js_content">
      <iframe data-mpvid="wxv_native123" title="原生片段"></iframe>
      <script>window.mp_video_trans_info = [{{
        "mpvid":"wxv_native123", "media_id":"media-1",
        "representations":[{{"url":"{signed_url}"}}]
      }}];</script>
      <iframe src="//v.qq.com/iframe/preview.html?vid=tencent123"></iframe>
      <mp-common-videosnap data-id="channels-1" data-title="视频号片段" />
      <video src="https://unknown.example/video.mp4?ticket=secret"></video>
    </body></html>
    """

    result = parse_article_html(payload)

    assert result.title == "安全文章"
    assert [item.kind for item in result.items] == [
        DiscoveryItemKind.OFFICIAL_ACCOUNT_NATIVE,
        DiscoveryItemKind.TENCENT_VIDEO,
        DiscoveryItemKind.WECHAT_CHANNELS,
        DiscoveryItemKind.UNKNOWN,
    ]
    assert result.items[0].decision_hint is DiscoveryDecisionHint.CANDIDATE
    assert result.items[0].status is DiscoveryItemStatus.READY
    assert result.items[2].decision_hint is DiscoveryDecisionHint.EXPORT_REQUIRED
    rendered = repr(result)
    assert signed_url not in rendered
    assert "token=secret" not in rendered
    assert "ticket=secret" not in rendered


def test_native_item_fails_closed_when_identity_mapping_is_ambiguous() -> None:
    payload = """
    <div id="js_content"><iframe data-mpvid="wxv_duplicate"></iframe></div>
    <script>mp_video_trans_info = [
      {"mpvid":"wxv_duplicate","media_id":"one","url":"https://mpvideo.qpic.cn/a.mp4"},
      {"mpvid":"wxv_duplicate","media_id":"two","url":"https://mpvideo.qpic.cn/b.mp4"}
    ];</script>
    """

    item = parse_article_html(payload).items[0]

    assert item.kind is DiscoveryItemKind.OFFICIAL_ACCOUNT_NATIVE
    assert item.status is DiscoveryItemStatus.IDENTITY_UNVERIFIED
    assert item.decision_hint is DiscoveryDecisionHint.UNSUPPORTED


def test_challenge_page_is_rejected_without_browser_fallback() -> None:
    with pytest.raises(ArticleAccessRestricted):
        parse_article_html("<html><title>安全验证</title>请输入验证码</html>")


def test_challenge_marker_after_bootstrap_script_is_rejected() -> None:
    payload = (
        '<html><head><title>文章标题</title></head><body id="js_content">'
        + ("x" * 20_000)
        + "环境异常，请完成验证后继续访问</body></html>"
    )

    with pytest.raises(ArticleAccessRestricted):
        parse_article_html(payload)


def test_missing_article_body_fails_closed() -> None:
    with pytest.raises(ArticleDiscoveryFailure):
        parse_article_html('<html><iframe src="https://v.qq.com/x/page/a123.html">')


@pytest.mark.asyncio
async def test_http_adapter_uses_bounded_html_request_without_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("cookie") is None
        assert request.headers["accept"] == "text/html"
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=(
                '<div id="js_content"><iframe '
                'src="https://v.qq.com/x/page/tencent123.html"></iframe></div>'
            ),
        )

    async def resolver(_: str) -> tuple[str, ...]:
        return ("1.1.1.1",)

    adapter = WeChatArticleDiscoveryAdapter(
        transport=httpx.MockTransport(handler), resolver=resolver
    )

    result = await adapter.discover(ARTICLE_URL)

    assert result.items[0].kind is DiscoveryItemKind.TENCENT_VIDEO


@pytest.mark.asyncio
async def test_http_adapter_rejects_private_resolution_and_oversized_html() -> None:
    async def private_resolver(_: str) -> tuple[str, ...]:
        return ("127.0.0.1",)

    adapter = WeChatArticleDiscoveryAdapter(resolver=private_resolver)
    with pytest.raises(ArticleDiscoveryFailure):
        await adapter.discover(ARTICLE_URL)

    async def public_resolver(_: str) -> tuple[str, ...]:
        return ("1.1.1.1",)

    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"x" * 2048,
        )
    )
    bounded = WeChatArticleDiscoveryAdapter(
        max_response_bytes=1024,
        transport=transport,
        resolver=public_resolver,
    )
    with pytest.raises(ArticleDiscoveryFailure):
        await bounded.discover(ARTICLE_URL)


@pytest.mark.asyncio
async def test_http_adapter_maps_challenge_redirect_to_access_restricted() -> None:
    async def resolver(_: str) -> tuple[str, ...]:
        return ("1.1.1.1",)

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            302,
            headers={"location": "https://mp.weixin.qq.com/mp/challenge?token=secret"},
            request=request,
        )
    )
    adapter = WeChatArticleDiscoveryAdapter(transport=transport, resolver=resolver)

    with pytest.raises(ArticleAccessRestricted):
        await adapter.discover(ARTICLE_URL)


@pytest.mark.asyncio
async def test_http_adapter_uses_hardened_proxy_without_local_target_dns() -> None:
    async def unexpected_resolver(_: str) -> tuple[str, ...]:
        raise AssertionError("proxy mode must delegate target DNS to the egress proxy")

    adapter = WeChatArticleDiscoveryAdapter(
        proxy_url="http://127.0.0.1:9",
        resolver=unexpected_resolver,
    )

    with pytest.raises(ArticleDiscoveryFailure):
        await adapter.discover(ARTICLE_URL)


def test_http_adapter_rejects_credentialed_proxy() -> None:
    with pytest.raises(ValueError):
        WeChatArticleDiscoveryAdapter(proxy_url="http://user:secret@proxy:3128")
