from __future__ import annotations

from pathlib import Path

import pytest
from app.workers.session.browser import SiteBrowser
from app.workers.session.contracts import LoginAction
from app.workers.session.login import LoginError, RemoteLogins

YUANBAO = "https://yuanbao.tencent.com/"


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        async def record(*args, **kwargs):
            self.calls.append((name, *args, *kwargs.values()))

        return record


class Page:
    def __init__(self, context: Context) -> None:
        self.context = context
        self.url = "about:blank"
        self.main_frame = object()
        self.mouse, self.keyboard = Recorder(), Recorder()
        self.routes: list = []

    async def route(self, pattern, handler) -> None:
        self.routes.append(handler)

    async def goto(self, url, wait_until):
        if self.context.fail:
            raise OSError("net::ERR_TIMED_OUT")
        self.url = url

    async def screenshot(self, type, quality):
        return b"jpeg"

    async def evaluate(self, script):
        return self.context.auth

    def is_closed(self) -> bool:
        return False


class Context:
    def __init__(self) -> None:
        self.pages: list[Page] = []
        self.auth: dict = {}
        self.fail = False
        self.closed = False
        self.store = [
            {
                "name": "hy_token",
                "value": "t",
                "domain": ".yuanbao.tencent.com",
                "path": "/",
                "expires": 4102444800,
            },
            {"name": "other", "value": "x", "domain": ".evil.com", "path": "/"},
        ]

    async def new_page(self) -> Page:
        self.pages.append(Page(self))
        return self.pages[-1]

    async def cookies(self):
        return list(self.store)

    def set_default_timeout(self, value) -> None:
        pass

    async def close(self) -> None:
        self.closed = True


class Chromium:
    def __init__(self) -> None:
        self.contexts: list[Context] = []
        self.launches: list[dict] = []
        self.fail = False

    async def launch_persistent_context(self, profile, **options):
        self.launches.append({"profile": profile, **options})
        context = Context()
        context.fail = self.fail
        self.contexts.append(context)
        return context


class Playwright:
    def __init__(self) -> None:
        self.chromium = Chromium()


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def make(tmp_path: Path):
    playwright, clock = Playwright(), Clock()
    browser = SiteBrowser(playwright, tmp_path, proxy="http://egress:3128")
    return RemoteLogins(browser, tmp_path, clock=clock), playwright, clock


def logged_in(context: Context) -> None:
    context.auth = {"userId": "u", "token": "t", "headers": {}}


async def test_login_runs_in_a_temporary_profile_and_replaces_the_site_profile(
    tmp_path,
):
    logins, playwright, _ = make(tmp_path)
    old = tmp_path / "weixin.qq.com"
    old.mkdir()
    (old / "stale").write_text("x")

    login_id = await logins.start("weixin.qq.com", None)

    launch = playwright.chromium.launches[0]
    assert launch["profile"].name.startswith(".login-")
    assert launch["viewport"] == {"width": 1280, "height": 800}
    context = playwright.chromium.contexts[0]
    assert context.pages[0].url == YUANBAO
    frame = await logins.frame(login_id)
    assert (frame.image, frame.host, frame.logged_in) == (
        b"jpeg",
        "yuanbao.tencent.com",
        False,
    )
    with pytest.raises(LoginError, match="login_incomplete"):
        await logins.finish(login_id)
    assert (old / "stale").exists()

    logged_in(context)
    assert (await logins.frame(login_id)).logged_in
    site, jar = await logins.finish(login_id)

    assert site == "weixin.qq.com"
    assert b"hy_token" in jar and b"evil" not in jar
    assert context.closed
    assert old.is_dir() and not (old / "stale").exists()
    assert [p.name for p in tmp_path.iterdir()] == ["weixin.qq.com"]
    with pytest.raises(LoginError, match="login_not_found"):
        await logins.frame(login_id)


async def test_actions_reach_the_page_in_order(tmp_path):
    logins, playwright, _ = make(tmp_path)
    login_id = await logins.start("weixin.qq.com", None)
    actions = [
        LoginAction(kind="click", x=10, y=20),
        LoginAction(kind="drag", x=1, y=2, x2=300, y2=2),
        LoginAction(kind="wheel", dy=-120),
        LoginAction(kind="type", text="abc"),
        LoginAction(kind="key", key="Enter"),
    ]

    await logins.act(login_id, actions)

    page = playwright.chromium.contexts[0].pages[0]
    assert page.mouse.calls == [
        ("click", 10, 20),
        ("move", 1, 2),
        ("down",),
        ("move", 300, 2, 25),
        ("up",),
        ("wheel", 0, -120),
    ]
    assert page.keyboard.calls == [("type", "abc", 40), ("press", "Enter")]


async def test_one_login_per_site_and_two_overall(tmp_path):
    logins, _, _ = make(tmp_path)
    await logins.start("weixin.qq.com", None)
    with pytest.raises(LoginError, match="login_busy"):
        await logins.start("weixin.qq.com", None)
    await logins.start("reddit.com", None)
    with pytest.raises(LoginError, match="login_busy"):
        await logins.start("youtube.com", None)


async def test_start_url_must_be_https_on_the_same_site(tmp_path):
    logins, playwright, _ = make(tmp_path)
    for url in (
        "http://media.example.com/login",
        "https://other.org/login",
        "https://127.0.0.1/",
    ):
        with pytest.raises(LoginError, match="login_url_invalid"):
            await logins.start("example.com", url)
    assert playwright.chromium.launches == []

    await logins.start("example.com", "https://media.example.com/login")
    assert playwright.chromium.contexts[0].pages[0].url.startswith("https://media")


async def test_idle_logins_are_cancelled_and_their_profiles_removed(tmp_path):
    logins, playwright, clock = make(tmp_path)
    login_id = await logins.start("weixin.qq.com", None)
    clock.now = 299
    await logins.sweep()
    await logins.frame(login_id)  # touching keeps it alive
    clock.now = 700
    await logins.sweep()

    with pytest.raises(LoginError, match="login_not_found"):
        await logins.frame(login_id)
    assert playwright.chromium.contexts[0].closed
    assert list(tmp_path.iterdir()) == []


async def test_failed_start_leaves_nothing_behind_and_frees_the_site(tmp_path):
    logins, playwright, _ = make(tmp_path)
    playwright.chromium.fail = True
    with pytest.raises(OSError):
        await logins.start("weixin.qq.com", None)
    assert list(tmp_path.iterdir()) == []
    playwright.chromium.fail = False
    await logins.start("weixin.qq.com", None)


async def test_navigation_guard_blocks_non_https_top_level_only(tmp_path):
    logins, playwright, _ = make(tmp_path)
    await logins.start("weixin.qq.com", None)
    page = playwright.chromium.contexts[0].pages[0]
    guard = page.routes[0]

    class Request:
        def __init__(self, url, navigation, frame):
            self.url, self._navigation, self.frame = url, navigation, frame

        def is_navigation_request(self):
            return self._navigation

    class Route:
        def __init__(self, request):
            self.request, self.result = request, None

        async def abort(self, reason):
            self.result = "abort"

        async def continue_(self):
            self.result = "continue"

    cases = [
        (Request("https://open.weixin.qq.com/x", True, page.main_frame), "continue"),
        (Request("http://intranet/", True, page.main_frame), "abort"),
        (Request("file:///etc/passwd", True, page.main_frame), "abort"),
        (Request("http://cdn/x.png", False, page.main_frame), "continue"),
    ]
    for request, expected in cases:
        route = Route(request)
        await guard(route)
        assert route.result == expected


def test_leftover_login_profiles_are_discarded(tmp_path):
    (tmp_path / ".login-old").mkdir()
    (tmp_path / "youtube.com").mkdir()
    logins, _, _ = make(tmp_path)
    logins.discard_leftovers()
    assert [p.name for p in tmp_path.iterdir()] == ["youtube.com"]


def test_actions_carry_exactly_the_fields_of_their_kind():
    with pytest.raises(ValueError):
        LoginAction(kind="click", x=1)
    with pytest.raises(ValueError):
        LoginAction(kind="type", text="a", x=1, y=1)
    with pytest.raises(ValueError):
        LoginAction(kind="click", x=1280, y=0)
    with pytest.raises(ValueError):
        LoginAction(kind="key", key="Meta")
