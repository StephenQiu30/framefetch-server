"""Bounded native browser resources owned by the existing media Runner.

Profiles contain browser state only. There is no task ledger, scheduler,
interactive login window or fallback account source in this module.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

from app.services.provider_failures import (
    FailureEvidenceKind,
    FailurePhase,
    FailureScope,
    parse_retry_after,
)
from app.services.provider_types import ExecutionContext
from app.workers.runner._secure_file import no_follow_flag
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.netscape_cookie import parse_cookie_payload
from app.workers.runner.provider_registry import ProviderProfile
from app.workers.runner.settings import RunnerSettings
from app.workers.runner.utilities import safe_media_url
from playwright._impl._api_structures import SetCookieParam
from playwright.async_api import (
    BrowserContext,
    Error,
    Page,
    async_playwright,
)

PLAYWRIGHT_VERSION = "1.63.0"
CHROMIUM_VERSION = "153.0.8010.12"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/{CHROMIUM_VERSION} Safari/537.36"
)
_LAUNCH_ARGS = (
    "--proxy-bypass-list=<-loopback>",
    "--disk-cache-size=16777216",
    "--media-cache-size=16777216",
)


def browser_revision(settings: RunnerSettings, provider_key: str) -> str:
    return sha256(
        json.dumps(
            {
                "playwright": PLAYWRIGHT_VERSION,
                "chromium": CHROMIUM_VERSION,
                "headless": True,
                "channel": "chromium",
                "user_agent": BROWSER_USER_AGENT,
                "args": _LAUNCH_ARGS,
                "service_workers": "block",
                "egress": settings.egress_proxy_for(provider_key),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _failure(code: str = "browser_unavailable", *, status: int = 503) -> RunnerFailure:
    return RunnerFailure(
        code,
        status=status,
        phase=FailurePhase.PREPARE_CONTEXT,
        scope=FailureScope.RUNTIME,
    )


def _private_root(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink() or not stat.S_ISDIR(path.lstat().st_mode):
        raise _failure()
    path.chmod(0o700)


def _profile_bytes(root: Path) -> int:
    return sum(
        path.lstat().st_size
        for path in root.rglob("*")
        if not path.is_symlink() and path.is_file()
    )


def leased_browser_cookies(jar: Path, profile: ProviderProfile) -> list[SetCookieParam]:
    """Read the approved per-operation jar, never a desktop browser database."""
    cookies: list[SetCookieParam] = []
    for entry in parse_cookie_payload(
        jar.read_bytes(), profile.cookie_domain_allowlist
    ):
        raw_domain, _, path, secure, expires, name, value = entry.line.split(b"\t")
        cookie: SetCookieParam = {
            "domain": raw_domain.removeprefix(b"#HttpOnly_").decode("ascii"),
            "path": path.decode("utf-8"),
            "secure": secure == b"TRUE",
            "httpOnly": raw_domain.startswith(b"#HttpOnly_"),
            "name": name.decode("utf-8"),
            "value": value.decode("utf-8"),
        }
        if int(expires) > 0:
            cookie["expires"] = int(expires)
        cookies.append(cookie)
    return cookies


@dataclass(frozen=True, slots=True)
class BrowserOperation:
    context: BrowserContext
    page: Page
    revision: str

    async def navigate(self, url: str) -> int:
        response = await self.page.goto(
            safe_media_url(url), wait_until="domcontentloaded"
        )
        if response is None:
            raise RunnerFailure("extractor_regression", status=502)
        status = response.status
        if status >= 400:
            code = {
                401: "login_required",
                404: "provider_link_unavailable",
                410: "provider_link_unavailable",
                429: "provider_rate_limited",
            }.get(status, "upstream_unclassified")
            raise RunnerFailure(
                code,
                status=502,
                phase=FailurePhase.FETCH_METADATA,
                evidence_kind=FailureEvidenceKind.UPSTREAM_RESPONSE,
                retry_after=parse_retry_after(
                    response.headers.get("retry-after"), datetime.now(UTC)
                ),
            )
        return status


class BrowserRuntime:
    """One browser holder at a time, with OS locks for persistent profiles."""

    def __init__(self, settings: RunnerSettings) -> None:
        self._settings = settings
        self._slot = asyncio.Lock()
        self._owners: set[asyncio.Task[object]] = set()
        self._closed = False

    @asynccontextmanager
    async def operation(
        self,
        profile: ProviderProfile,
        execution_context: ExecutionContext,
        *,
        cookie_jar: Path | None = None,
    ) -> AsyncIterator[BrowserOperation]:
        if self._closed or not self._settings.runner_browser_enabled:
            raise _failure()
        if version("playwright") != PLAYWRIGHT_VERSION:
            raise _failure("runtime_unavailable", status=409)
        if profile.key != execution_context.provider_key:
            raise _failure("runtime_unavailable", status=409)
        if execution_context.identity_used != (cookie_jar is not None):
            raise _failure("invalid_input", status=422)
        revision = browser_revision(self._settings, profile.key)
        try:
            await asyncio.wait_for(
                self._slot.acquire(), self._settings.runner_browser_lock_wait_seconds
            )
        except TimeoutError:
            raise _failure("browser_capacity_exhausted") from None
        owner = asyncio.current_task()
        assert owner is not None
        self._owners.add(owner)
        resources_ready = False
        try:
            if self._closed:
                raise _failure()
            async with self._directory(profile) as directory:
                async with async_playwright() as driver:
                    context: BrowserContext | None = None
                    try:
                        context = await driver.chromium.launch_persistent_context(
                            str(directory),
                            channel="chromium",
                            headless=True,
                            chromium_sandbox=False,
                            args=list(_LAUNCH_ARGS),
                            proxy={
                                "server": self._settings.egress_proxy_for(profile.key)
                            },
                            user_agent=BROWSER_USER_AGENT,
                            service_workers="block",
                            accept_downloads=False,
                            timeout=self._settings.runner_browser_launch_timeout_seconds
                            * 1000,
                            viewport={"width": 1280, "height": 800},
                        )
                        browser = context.browser
                        if browser is None or browser.version != CHROMIUM_VERSION:
                            raise _failure("runtime_unavailable", status=409)
                        if cookie_jar is not None:
                            await context.add_cookies(
                                leased_browser_cookies(cookie_jar, profile)
                            )
                        context.set_default_timeout(
                            self._settings.runner_browser_page_timeout_seconds * 1000
                        )
                        page = (
                            context.pages[0]
                            if context.pages
                            else await context.new_page()
                        )
                        for extra in context.pages[1:]:
                            await extra.close()
                        resources_ready = True
                        yield BrowserOperation(context, page, revision)
                    except Error:
                        if resources_ready:
                            raise
                        raise _failure() from None
                    finally:
                        if context is not None:
                            # A receipt is terminal only after Chromium releases
                            # pages/profile/processes. Cancellation waits for this.
                            cleanup = asyncio.create_task(context.close())
                            try:
                                await asyncio.shield(cleanup)
                            except asyncio.CancelledError:
                                await cleanup
                                raise
        except OSError:
            if resources_ready:
                raise
            raise _failure() from None
        finally:
            self._owners.discard(owner)
            self._slot.release()

    @asynccontextmanager
    async def _directory(self, profile: ProviderProfile) -> AsyncIterator[Path]:
        root = self._settings.runner_browser_profile_root
        _private_root(root)
        identity = profile.key
        # The OS lock is a running-resource guard, not persisted task ownership.
        descriptor = os.open(
            root / f"{identity}.lock", os.O_CREAT | os.O_RDWR | no_follow_flag(), 0o600
        )
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise _failure("browser_capacity_exhausted") from None
            directory = root / identity
            _private_root(directory)
            if (
                await asyncio.to_thread(_profile_bytes, directory)
                > self._settings.runner_browser_max_profile_bytes
            ):
                raise _failure("browser_profile_limit", status=413)
            yield directory
            if (
                await asyncio.to_thread(_profile_bytes, directory)
                > self._settings.runner_browser_max_profile_bytes
            ):
                raise _failure("browser_profile_limit", status=413)
        finally:
            os.close(descriptor)

    async def close(self) -> None:
        self._closed = True
        current = asyncio.current_task()
        owners = tuple(owner for owner in self._owners if owner is not current)
        for owner in owners:
            owner.cancel()
        await asyncio.gather(*owners, return_exceptions=True)
