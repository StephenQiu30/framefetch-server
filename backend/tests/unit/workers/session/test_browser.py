from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.integrations.site_session_catalog import site_target
from app.workers.session import browser as module
from app.workers.session.browser import HeadersUnavailable, SiteBrowser
from app.workers.session.contracts import BrowserOutcome as O
from playwright.async_api import Error as PlaywrightError

YOUTUBE_JAR = (
    b"# Netscape HTTP Cookie File\n"
    b"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t4102444800\tSAPISID\ta\n"
    b".youtube.com\tTRUE\t/\tFALSE\t0\tPREF\tb\n"
)


class Response:
    def __init__(self, status: int) -> None:
        self.status = status


class Page:
    def __init__(self, context: Context) -> None:
        self.context = context
        self.main_frame = object()
        self.visited: list[str] = []

    async def route(self, pattern, handler) -> None:
        self.context.routes.append(handler)

    async def goto(self, url, wait_until):
        self.visited.append(url)
        if self.context.fail:
            raise PlaywrightError("net::ERR_TIMED_OUT")
        return Response(self.context.status)

    async def evaluate(self, script):
        return self.context.evaluations.pop(0)


class Context:
    def __init__(self) -> None:
        self.cookie_store: list[dict] = []
        self.evaluations: list[object] = []
        self.status = 200
        self.fail = False
        self.routes: list = []
        self.pages: list[Page] = []
        self.closed = False

    async def new_page(self) -> Page:
        page = Page(self)
        self.pages.append(page)
        return page

    async def clear_cookies(self) -> None:
        self.cookie_store = []

    async def add_cookies(self, cookies) -> None:
        self.cookie_store += cookies

    async def cookies(self):
        return list(self.cookie_store)

    def set_default_timeout(self, value) -> None:
        pass

    async def close(self) -> None:
        self.closed = True


class Chromium:
    def __init__(self, context: Context) -> None:
        self.context = context
        self.launches: list[dict] = []

    async def launch_persistent_context(self, profile, **options):
        self.launches.append({"profile": profile, **options})
        return self.context


class Playwright:
    def __init__(self, context: Context) -> None:
        self.chromium = Chromium(context)


def make(tmp_path: Path, context: Context | None = None):
    context = context or Context()
    playwright = Playwright(context)
    return (
        SiteBrowser(playwright, tmp_path, proxy="http://egress:3128"),
        context,
        playwright,
    )


async def test_bootstrap_replaces_cookies_probes_and_exports_sorted_jar(tmp_path):
    browser, context, playwright = make(tmp_path)
    context.cookie_store = [{"name": "stale", "value": "x", "domain": ".youtube.com"}]
    context.evaluations.append(True)

    result = await browser.bootstrap("youtube.com", YOUTUBE_JAR)

    assert result.outcome is O.VERIFIED
    launch = playwright.chromium.launches[0]
    assert launch["profile"] == tmp_path / "youtube.com" and launch["headless"]
    assert launch["proxy"] == {"server": "http://egress:3128"}
    assert (tmp_path / "youtube.com").stat().st_mode & 0o777 == 0o700
    assert [c["name"] for c in context.cookie_store] == ["SAPISID", "PREF"]
    sapisid = context.cookie_store[0]
    assert (
        sapisid["httpOnly"]
        and sapisid["secure"]
        and sapisid["domain"] == ".youtube.com"
    )
    assert context.cookie_store[1]["expires"] == -1
    assert context.pages[0].visited == ["https://www.youtube.com/feed/you"]
    assert result.jar.splitlines()[1:] == [
        b".youtube.com\tTRUE\t/\tFALSE\t0\tPREF\tb",
        b"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t4102444800\tSAPISID\ta",
    ]
    assert context.closed


async def test_outcomes(tmp_path):
    browser, context, _ = make(tmp_path)
    context.evaluations.append(False)
    assert (await browser.bootstrap("youtube.com", YOUTUBE_JAR)).outcome is O.LOGGED_OUT

    context.status = 429
    result = await browser.keepalive("youtube.com")
    assert (result.outcome, result.error_code) == (O.AUTH_FAILURE, "egress_challenged")

    context.status, context.fail = 200, True
    assert (await browser.keepalive("youtube.com")).outcome is O.UNAVAILABLE
    assert (await browser.keepalive("reddit.com")).outcome is O.PROFILE_MISSING


async def test_cookie_probe_uses_registry_rules_for_other_sites(tmp_path):
    browser, context, _ = make(tmp_path)
    jar = (
        b"# Netscape HTTP Cookie File\n"
        b".reddit.com\tTRUE\t/\tTRUE\t4102444800\treddit_session\tx\n"
    )
    assert (await browser.bootstrap("reddit.com", jar)).outcome is O.VERIFIED
    context.cookie_store = [
        {
            "name": "reddit_session",
            "value": "x",
            "domain": ".reddit.com",
            "path": "/",
            "expires": -1,
        }
    ]
    # Only a session cookie is left: the persistent login is gone.
    assert (await browser.keepalive("reddit.com")).outcome is O.LOGGED_OUT


async def test_jars_for_other_domains_are_rejected(tmp_path):
    browser, _, _ = make(tmp_path)
    with pytest.raises(ValueError):
        await browser.bootstrap(
            "youtube.com",
            b"# Netscape HTTP Cookie File\n.evil.com\tTRUE\t/\tTRUE\t0\tSID\tx\n",
        )


async def test_only_top_level_navigation_is_restricted(tmp_path):
    browser, context, _ = make(tmp_path)
    context.evaluations.append(True)
    await browser.bootstrap("youtube.com", YOUTUBE_JAR)
    guard = context.routes[0]
    page = context.pages[0]

    class Request:
        def __init__(self, url, navigation, frame):
            self.url, self._navigation, self.frame = url, navigation, frame

        def is_navigation_request(self):
            return self._navigation

    class Route:
        def __init__(self, request):
            self.request, self.result = request, None

        async def abort(self, reason):
            self.result = reason

        async def continue_(self):
            self.result = "continue"

    cases = [
        ("https://m.youtube.com/", True, page.main_frame, "continue"),
        ("https://evil.example/", True, page.main_frame, "blockedbyclient"),
        ("https://i.ytimg.com/a.jpg", False, page.main_frame, "continue"),
        ("https://ads.example/", True, object(), "continue"),
    ]
    for url, navigation, frame, expected in cases:
        route = Route(Request(url, navigation, frame))
        await guard(route)
        assert route.result == expected, url


async def test_yuanbao_headers(tmp_path):
    browser, context, _ = make(tmp_path)
    with pytest.raises(HeadersUnavailable):
        await browser.headers("weixin.qq.com")
    (tmp_path / "weixin.qq.com").mkdir()
    context.evaluations.append(
        {"userId": "u", "token": "t", "headers": {"x-hy92": "1"}, "extra": "dropped"}
    )
    payload = json.loads(await browser.headers("weixin.qq.com"))
    assert payload == {"userId": "u", "token": "t", "headers": {"x-hy92": "1"}}
    assert context.pages[0].visited == ["https://yuanbao.tencent.com/"]
    context.evaluations.append({"userId": "", "token": "t"})
    with pytest.raises(HeadersUnavailable):
        await browser.headers("weixin.qq.com")
    with pytest.raises(HeadersUnavailable):
        await browser.headers("youtube.com")


async def test_forget_removes_only_valid_profiles(tmp_path):
    browser, _, _ = make(tmp_path)
    (tmp_path / "youtube.com" / "Default").mkdir(parents=True)
    await browser.forget("youtube.com")
    assert not (tmp_path / "youtube.com").exists()
    await browser.forget("youtube.com")
    with pytest.raises(ValueError):
        await browser.forget("localhost")


def test_export_filters_foreign_and_empty_cookies():
    import asyncio

    context = Context()
    context.cookie_store = [
        {
            "name": "a",
            "value": "1",
            "domain": ".youtube.com",
            "path": "/",
            "expires": 5,
        },
        {"name": "b", "value": "", "domain": ".youtube.com", "path": "/"},
        {"name": "c", "value": "1", "domain": ".google.com", "path": "/"},
    ]
    jar = asyncio.run(module.export_jar(context, site_target("youtube.com")))
    assert jar.splitlines()[1:] == [b".youtube.com\tTRUE\t/\tFALSE\t5\ta\t1"]
