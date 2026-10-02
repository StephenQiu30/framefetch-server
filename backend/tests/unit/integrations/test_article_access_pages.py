import pytest
from app.integrations.article_discovery.parser import parse_article_html
from app.services.source_discoveries.ports import ArticleAccessRestricted


@pytest.mark.parametrize(
    "marker", ["安全验证", "环境异常", "请输入验证码", "登录后继续"]
)
def test_article_can_discuss_access_messages(marker: str) -> None:
    payload = (
        '<html><title>使用说明</title><body><div id="js_content">'
        + "x" * 20_000
        + f"<p>本节介绍{marker}的使用方法。</p>"
        + '<iframe src="https://v.qq.com/x/page/abcd1234.html"></iframe>'
        + "</div></body></html>"
    )
    assert len(parse_article_html(payload).items) == 1


def test_script_messages_do_not_restrict_an_article() -> None:
    payload = (
        '<script>const messages = ["安全验证", "请输入验证码"];</script>'
        '<div id="js_content"><p>正常文章</p></div>'
    )
    assert parse_article_html(payload).items == ()


def test_article_can_quote_a_complete_challenge_instruction() -> None:
    payload = '<div id="js_content"><p>环境异常，请完成验证后继续访问</p></div>'
    assert parse_article_html(payload).items == ()


def test_article_title_can_name_security_verification() -> None:
    payload = (
        "<html><title>安全验证</title><body>"
        '<div id="js_content"><p>教程</p></div></body></html>'
    )
    assert parse_article_html(payload).title == "安全验证"


def test_visible_challenge_after_large_script_is_rejected() -> None:
    payload = (
        "<html><body><script>"
        + "x" * 20_000
        + "</script><div>环境异常，请完成验证后继续访问</div></body></html>"
    )
    with pytest.raises(ArticleAccessRestricted):
        parse_article_html(payload)
