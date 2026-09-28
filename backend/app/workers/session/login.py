"""Remote login: an administrator drives a site's browser from the admin page.

Each login runs in its own temporary profile. Only a login that passes the
site's login check replaces the site's profile, so an abandoned or failed login
never disturbs a working session. Nothing here solves challenges: every scan,
slider and password comes from the human watching the frames.
"""

from __future__ import annotations

import asyncio
import secrets
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from app.integrations.site_session_catalog import (
    SiteTarget,
    site_target,
    site_target_for_url,
)
from app.services.site_sessions import InvalidSessionSite
from app.workers.runner.errors import RunnerFailure
from app.workers.session.browser import SiteBrowser, export_jar
from app.workers.session.contracts import LOGIN_HEIGHT, LOGIN_WIDTH, LoginAction
from app.workers.session.seeding import seedable_payload
from playwright.async_api import BrowserContext, Page, Route

IDLE_SECONDS = 300
MAX_LOGINS = 2
_PREFIX = ".login-"
_DRAG_STEPS = 25
_TYPE_DELAY_MS = 40


class LoginError(Exception):
    """A request the login cannot serve; ``code`` is safe to return."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Frame:
    image: bytes
    host: str
    logged_in: bool


@dataclass(slots=True)
class _Login:
    site: str
    target: SiteTarget
    profile: Path
    context: BrowserContext
    touched: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RemoteLogins:
    def __init__(
        self,
        browser: SiteBrowser,
        root: Path,
        *,
        idle_seconds: float = IDLE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._browser = browser
        self._root = root
        self._idle = idle_seconds
        self._clock = clock
        self._logins: dict[str, _Login] = {}
        self._starting: set[str] = set()

    def discard_leftovers(self) -> None:
        """Remove profiles of logins a previous process never finished."""
        if not self._root.is_dir():
            return
        for entry in self._root.iterdir():
            if entry.name.startswith(_PREFIX):
                shutil.rmtree(entry, ignore_errors=True)

    async def start(self, site: str, url: str | None) -> str:
        target = site_target(site)
        start_url = _start_url(target, url)
        if site in self._starting or any(
            login.site == site for login in self._logins.values()
        ):
            raise LoginError("login_busy")
        if len(self._logins) + len(self._starting) >= MAX_LOGINS:
            raise LoginError("login_busy")
        self._starting.add(site)
        login_id = secrets.token_urlsafe(16)
        profile = self._root / f"{_PREFIX}{login_id}"
        context: BrowserContext | None = None
        try:
            profile.mkdir(mode=0o700, parents=True)
            context = await self._browser.launch_profile(
                profile, viewport={"width": LOGIN_WIDTH, "height": LOGIN_HEIGHT}
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.route("**/*", _https_only(page))
            await page.goto(start_url, wait_until="domcontentloaded")
        except BaseException:
            if context is not None:
                await context.close()
            shutil.rmtree(profile, ignore_errors=True)
            raise
        finally:
            self._starting.discard(site)
        self._logins[login_id] = _Login(site, target, profile, context, self._clock())
        return login_id

    async def frame(self, login_id: str) -> Frame:
        login = self._get(login_id)
        async with login.lock:
            page = _current_page(login.context)
            image = await page.screenshot(type="jpeg", quality=60)
            logged_in = await self._browser.logged_in(page, login.context, login.target)
            return Frame(image, urlsplit(page.url).hostname or "", logged_in)

    async def act(self, login_id: str, actions: Sequence[LoginAction]) -> None:
        login = self._get(login_id)
        async with login.lock:
            page = _current_page(login.context)
            for action in actions:
                await _perform(page, action)

    async def finish(self, login_id: str) -> tuple[str, bytes]:
        """Return the site and its exported jar, then adopt the profile."""
        login = self._get(login_id)
        async with login.lock:
            page = _current_page(login.context)
            if not await self._browser.logged_in(page, login.context, login.target):
                raise LoginError("login_incomplete")
            jar = await export_jar(login.context, login.target)
            # The page can look logged in while the site keeps its login out of
            # cookies; such a login cannot become a seed, so keep the old profile.
            if seedable_payload(jar, login.target, time.time()) is None:
                raise LoginError("login_not_accepted")
            await login.context.close()
            self._logins.pop(login_id, None)
            await self._browser.adopt_profile(login.site, login.profile)
            return login.site, jar

    async def cancel(self, login_id: str) -> None:
        login = self._logins.pop(login_id, None)
        if login is not None:
            await _discard(login)

    async def sweep(self) -> None:
        cutoff = self._clock() - self._idle
        for login_id, login in list(self._logins.items()):
            if login.touched < cutoff and not login.lock.locked():
                await self.cancel(login_id)

    async def close(self) -> None:
        for login_id in list(self._logins):
            await self.cancel(login_id)

    def _get(self, login_id: str) -> _Login:
        login = self._logins.get(login_id)
        if login is None:
            raise LoginError("login_not_found")
        login.touched = self._clock()
        return login


def _start_url(target: SiteTarget, url: str | None) -> str:
    if url is None:
        return target.policy.keepalive_url
    parts = urlsplit(url)
    try:
        same_site = parts.scheme == "https" and (
            site_target_for_url(url).site == target.site
        )
    except (InvalidSessionSite, RunnerFailure):
        same_site = False
    if not same_site:
        raise LoginError("login_url_invalid")
    return url


def _https_only(page: Page):  # type: ignore[no-untyped-def]
    """SSO flows leave the site, but never for plain HTTP or local schemes."""

    async def guard(route: Route) -> None:
        request = route.request
        scheme = urlsplit(request.url).scheme
        if (
            request.is_navigation_request()
            and request.frame == page.main_frame
            and scheme not in {"https", "about"}
        ):
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    return guard


def _current_page(context: BrowserContext) -> Page:
    pages = [page for page in context.pages if not page.is_closed()]
    if not pages:
        raise LoginError("login_not_found")
    return pages[-1]


async def _perform(page: Page, action: LoginAction) -> None:
    mouse, keyboard = page.mouse, page.keyboard
    # ``LoginAction`` guarantees exactly the fields each kind needs.
    x, y, x2, y2 = action.x or 0, action.y or 0, action.x2 or 0, action.y2 or 0
    match action.kind:
        case "click":
            await mouse.click(x, y)
        case "drag":
            await mouse.move(x, y)
            await mouse.down()
            await mouse.move(x2, y2, steps=_DRAG_STEPS)
            await mouse.up()
        case "wheel":
            await mouse.wheel(0, action.dy or 0)
        case "type":
            await keyboard.type(action.text or "", delay=_TYPE_DELAY_MS)
        case "key":
            await keyboard.press(action.key or "Enter")


async def _discard(login: _Login) -> None:
    try:
        await login.context.close()
    finally:
        await asyncio.to_thread(shutil.rmtree, login.profile, True)
