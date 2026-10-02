"""Bounded native browser resources owned by the existing media Runner.

Profiles contain browser state only. There is no task ledger, scheduler,
interactive login window or fallback account source in this module.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
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
from app.workers.identity.yuanbao_account import validate_yuanbao_account_material
from app.workers.runner._secure_file import no_follow_flag
from app.workers.runner.engine.egress import EgressBinding
from app.workers.runner.engine.identity import (
    IdentityMaterial,
    YuanbaoAccountMaterial,
    _is_tmpfs,
)
from app.workers.runner.engine.run_context import RunContext
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
    Playwright,
    async_playwright,
)
from playwright.async_api._context_manager import PlaywrightContextManager

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
    "--autoplay-policy=user-gesture-required",
)


def browser_revision(egress: EgressBinding) -> str:
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
                "egress": egress.revision,
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


def _private_temp_root(path: Path) -> Path:
    """Account state must never reach the anonymous persistent volume."""
    if not path.is_absolute() or path == Path("/"):
        raise _failure()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise _failure()
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    metadata = path.stat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or not _is_tmpfs(path)
    ):
        raise _failure()
    return path


def initialize_browser_tmpfs(path: Path) -> None:
    """Before accepting operations, remove state left by a crashed Runner."""
    root = _private_temp_root(path)
    for item in root.iterdir():
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()


def _yuanbao_bootstrap(material: YuanbaoAccountMaterial) -> str:
    # add_init_script runs again after navigation and inside frames. Both checks
    # belong in the script itself, before any account value is written.
    values = json.dumps(
        {
            "account": material.account_id.get_secret_value(),
            "token": material.auth_token.get_secret_value(),
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return (
        "(() => { if (top !== self || location.origin !== "
        "'https://yuanbao.tencent.com') return; const material = "
        + values
        + "; localStorage.setItem('yb_user_id', material.account); "
        "localStorage.setItem('yb_token', material.token); })();"
    )


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
    release: Callable[[], Awaitable[None]] = field(repr=False)
    abort: Callable[[], Awaitable[None]] = field(repr=False)
    max_download_bytes: int = 512 * 1024**2

    @property
    def user_agent(self) -> str:
        return BROWSER_USER_AGENT

    async def cookies(self) -> list[dict[str, object]]:
        return [dict(cookie) for cookie in await self.context.cookies()]

    async def download(self, url: str, dest: Path) -> None:
        # A page fetch executes in the same native context, including its proofs.
        # Creating a blob download also works for cross-origin inline MP4s.
        async with self.page.expect_download() as pending:
            await self.page.evaluate(
                """async ({url, limit}) => {
                  const response = await fetch(url, {credentials: 'include'});
                  if (!response.ok || !response.body) throw new Error('media transfer');
                  if (Number(response.headers.get('content-length')) > limit)
                    throw new Error('media size');
                  const reader = response.body.getReader();
                  const chunks = []; let size = 0;
                  try {
                    for (;;) {
                      const {done, value} = await reader.read();
                      if (done) break;
                      size += value.byteLength;
                      if (size > limit) throw new Error('media size');
                      chunks.push(value);
                    }
                  } finally { await reader.cancel(); }
                  const blob = URL.createObjectURL(new Blob(chunks));
                  const a = document.createElement('a');
                  a.href = blob; a.download = 'media.mp4'; a.click();
                  setTimeout(() => URL.revokeObjectURL(blob), 60000);
                }""",
                {"url": safe_media_url(url), "limit": self.max_download_bytes},
            )
        download = await pending.value
        await download.save_as(str(dest))
        if (
            await download.failure() is not None
            or not dest.is_file()
            or dest.is_symlink()
        ):
            raise RunnerFailure("download_failed", status=502, stage="download")

    async def close(self) -> None:
        await self.release()

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


@dataclass(slots=True)
class _Resident:
    context: BrowserContext
    revision: str
    directory: Path
    descriptor: int | None
    idle: asyncio.Task[None] | None = None


class BrowserRuntime:
    """Lazily leased anonymous profiles; authenticated profiles never persist."""

    IDLE_SECONDS = 600.0

    def __init__(self, settings: RunnerSettings) -> None:
        self._settings = settings
        self._locks: dict[str, asyncio.Lock] = {}
        self._residents: dict[str, _Resident] = {}
        self._owners: set[asyncio.Task[object]] = set()
        self._releases: set[Callable[[], Awaitable[None]]] = set()
        self._driver_manager: PlaywrightContextManager | None = None
        self._driver: Playwright | None = None
        self._start_lock = asyncio.Lock()
        self._closed = False

    async def acquire(
        self, profile: ProviderProfile, *, ctx: RunContext
    ) -> BrowserOperation:
        if self._closed or not self._settings.runner_browser_enabled:
            raise _failure()
        if version("playwright") != PLAYWRIGHT_VERSION:
            raise _failure("runtime_unavailable", status=409)
        authenticated = ctx.identity is not None
        if ctx.cookie_file is not None and not authenticated:
            raise _failure("invalid_input", status=422)
        if authenticated:
            assert ctx.identity is not None
            if isinstance(ctx.identity, IdentityMaterial):
                from app.workers.runner.engine.identity import validate_cookie_file

                if profile.identity_source != "cookies":
                    raise _failure("invalid_input", status=422)
                validate_cookie_file(ctx.identity.cookie_file)
            else:
                if (
                    profile.key != "wechat_channels"
                    or profile.identity_source != "yuanbao_account"
                    or profile.identity_origin != "https://yuanbao.tencent.com"
                    or ctx.cookie_file is not None
                ):
                    raise _failure("invalid_input", status=422)
                try:
                    validate_yuanbao_account_material(
                        ctx.identity, deadline=ctx.deadline
                    )
                except ValueError:
                    raise _failure("invalid_input", status=422) from None
        lock = (
            asyncio.Lock()
            if authenticated
            else self._locks.setdefault(profile.key, asyncio.Lock())
        )
        remaining = (ctx.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise _failure("inspection_timeout", status=504)
        try:
            await asyncio.wait_for(lock.acquire(), remaining)
        except TimeoutError:
            raise _failure("inspection_timeout", status=504) from None
        owner = asyncio.current_task()
        assert owner is not None
        self._owners.add(owner)
        resident: _Resident | None = None
        released = False

        async def release(*, destroy: bool = False) -> None:
            nonlocal released
            if released:
                return
            released = True
            try:
                if resident is not None:
                    if authenticated or destroy or owner.cancelling() or self._closed:
                        if not authenticated:
                            self._residents.pop(profile.key, None)
                        await self._destroy(resident)
                    else:
                        try:
                            for page in tuple(resident.context.pages):
                                await _finish(page.close())
                            if await asyncio.to_thread(
                                _profile_bytes, resident.directory
                            ) > (self._settings.runner_browser_max_profile_bytes):
                                raise _failure("browser_profile_limit", status=413)
                            resident.idle = asyncio.create_task(
                                self._expire(profile.key, resident, lock)
                            )
                        except BaseException:
                            self._residents.pop(profile.key, None)
                            await self._destroy(resident)
                            raise
            finally:
                self._owners.discard(owner)
                self._releases.discard(release)
                lock.release()

        self._releases.add(release)
        try:
            if self._closed:
                raise _failure()
            revision = browser_revision(ctx.egress)
            if not authenticated:
                resident = self._residents.get(profile.key)
                if resident is not None:
                    if resident.idle is not None:
                        resident.idle.cancel()
                        resident.idle = None
                    if resident.revision != revision:
                        await self._destroy(resident)
                        self._residents.pop(profile.key, None)
                        resident = None
            if resident is None:
                resident = await self._launch(profile, ctx, authenticated)
                if not authenticated:
                    self._residents[profile.key] = resident
            page = await resident.context.new_page()

            async def abort() -> None:
                await release(destroy=True)

            return BrowserOperation(resident.context, page, revision, release, abort)
        except BaseException:
            await _finish(release(destroy=True))
            raise

    async def _launch(
        self,
        profile: ProviderProfile,
        ctx: RunContext,
        authenticated: bool,
    ) -> _Resident:
        descriptor = None
        context = None
        root = (
            self._settings.runner_browser_temp_root
            if authenticated
            else self._settings.runner_browser_profile_root / "anonymous"
        )
        if authenticated:
            _private_temp_root(root)
            directory = Path(tempfile.mkdtemp(prefix=f"{profile.key}-", dir=root))
        else:
            _private_root(root)
            descriptor = os.open(
                root / f"{profile.key}.lock",
                os.O_CREAT | os.O_RDWR | no_follow_flag(),
                0o600,
            )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(descriptor)
                raise _failure("browser_capacity_exhausted") from None
            directory = root / profile.key
        try:
            _private_root(directory)
            if await asyncio.to_thread(_profile_bytes, directory) > (
                self._settings.runner_browser_max_profile_bytes
            ):
                raise _failure("browser_profile_limit", status=413)
            async with self._start_lock:
                if self._driver is None:
                    self._driver_manager = async_playwright()
                    self._driver = await self._driver_manager.__aenter__()
            context = await self._driver.chromium.launch_persistent_context(
                str(directory),
                channel="chromium",
                headless=True,
                chromium_sandbox=False,
                args=list(_LAUNCH_ARGS),
                proxy={"server": ctx.egress.proxy_url},
                user_agent=BROWSER_USER_AGENT,
                service_workers="block",
                accept_downloads=True,
                timeout=self._settings.runner_browser_launch_timeout_seconds * 1000,
                viewport={"width": 1280, "height": 800},
            )
            if context.browser is None or context.browser.version != CHROMIUM_VERSION:
                raise _failure("runtime_unavailable", status=409)
            if authenticated:
                assert ctx.identity is not None
                if isinstance(ctx.identity, IdentityMaterial):
                    await context.add_cookies(
                        leased_browser_cookies(ctx.identity.cookie_file, profile)
                    )
                else:
                    await context.add_init_script(_yuanbao_bootstrap(ctx.identity))
            context.set_default_timeout(
                self._settings.runner_browser_page_timeout_seconds * 1000
            )
            for page in context.pages:
                await page.close()
            return _Resident(
                context,
                browser_revision(ctx.egress),
                directory,
                descriptor,
            )
        except BaseException as error:
            try:
                if context is not None:
                    try:
                        await _finish(context.close())
                    except (Error, OSError):
                        # Preserve the safe primary failure when cleanup hits
                        # a disconnected driver; release storage and locks below.
                        pass
            finally:
                try:
                    if descriptor is not None:
                        os.close(descriptor)
                finally:
                    if authenticated:
                        shutil.rmtree(directory)
            if isinstance(error, (Error, OSError)):
                raise _failure() from None
            raise

    async def _destroy(self, resident: _Resident) -> None:
        try:
            await _finish(resident.context.close())
        finally:
            if resident.descriptor is not None:
                os.close(resident.descriptor)
                resident.descriptor = None
            elif resident.directory.is_relative_to(
                self._settings.runner_browser_temp_root
            ):
                await asyncio.to_thread(shutil.rmtree, resident.directory)

    async def _expire(self, key: str, resident: _Resident, lock: asyncio.Lock) -> None:
        await asyncio.sleep(self.IDLE_SECONDS)
        async with lock:
            if self._residents.get(key) is resident:
                self._residents.pop(key)
                await self._destroy(resident)

    async def close(self) -> None:
        self._closed = True
        current = asyncio.current_task()
        owners = tuple(owner for owner in self._owners if owner is not current)
        for owner in owners:
            owner.cancel()
        await asyncio.gather(*owners, return_exceptions=True)
        for release in tuple(self._releases):
            await _finish(release())
        for resident in tuple(self._residents.values()):
            if resident.idle is not None:
                resident.idle.cancel()
            await self._destroy(resident)
        self._residents.clear()
        if self._driver_manager is not None:
            await self._driver_manager.__aexit__(None, None, None)
            self._driver = None


async def _finish(operation: Awaitable[None]) -> None:
    cleanup = asyncio.ensure_future(operation)
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            await asyncio.shield(cleanup)
            break
        except asyncio.CancelledError as error:
            if cleanup.done():
                # The cleanup itself may have been cancelled. Inspect it once
                # rather than repeatedly shielding a terminal cancelled task.
                cleanup.result()
                cancellation = error
                break
            # More than one caller can cancel an operation during shutdown.
            # Each external cancellation must leave native cleanup shielded.
            cancellation = error
    if cancellation is not None:
        raise cancellation
