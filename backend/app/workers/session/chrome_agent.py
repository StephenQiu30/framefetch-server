"""Host agent: hand out the operator's live Chrome login state on demand.

FrameFetch is a single-user tool. The Chrome the operator uses every day is the
only source of platform login state: nothing is copied into the database or a
second browser, so the platform keeps rotating one session in one place. The
container broker asks this agent for one site's Cookies right before a Runner
operation; the reply is sealed to the broker's per-request key.

    uv run python -m app.workers.session.chrome_agent install   # once, macOS
    uv run python -m app.workers.session.chrome_agent check     # diagnose
    uv run python -m app.workers.session.chrome_agent uninstall

``install`` registers a KeepAlive LaunchAgent. The Python it runs needs macOS
Full Disk Access (Chrome data folder) and "Always Allow" on the
"Chrome Safe Storage" keychain item; ``check`` names the exact binary.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import IntEnum
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from typing import Annotated, Final

import uvicorn
from app.integrations.site_session_catalog import SiteTarget, site_target
from app.services.site_sessions import (
    InvalidSessionSite,
    SiteSessionPolicy,
    known_session_sites,
)
from app.workers.runner.netscape_cookie import (
    has_safe_cookie_fields,
    is_allowed_domain,
    serialize_cookies,
)
from app.workers.session.chrome_reader import (
    DEFAULT_CHROME_ROOT,
    ChromeProfile,
    chrome_profiles,
    extract_chrome_cookies,
)
from app.workers.session.page_headers import PageHeadersUnavailable, page_headers
from app.workers.session.rpc import authenticator, verified_model
from app.workers.session.sealing import SealError, decode_public_key, encode, seal
from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StringConstraints

PROJECT_ROOT = Path(__file__).resolve().parents[4]
AGENT_PORT: Final = 19250
COOKIES_PATH: Final = "/v1/cookies"
AGENT_LABEL: Final = "com.framefetch.chrome-agent"
_PROFILE_NAME: Final = re.compile(r"(?:Default|Profile [1-9][0-9]*)")
# Chrome rewrites its Cookie database continuously; a short cache only absorbs
# the status + lease pair of one operation.
_CACHE_SECONDS: Final = 20.0


class ExitCode(IntEnum):
    OK = 0
    ACTION_REQUIRED = 2
    PERMISSION_DENIED = 3
    UNAVAILABLE = 4


class ChromeSourceError(Exception):
    def __init__(self, code: ExitCode, reason: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ChromeLogin:
    profile: ChromeProfile
    cookies: tuple[Cookie, ...]


type CookieExtractor = Callable[..., CookieJar]


def read_login(
    target: SiteTarget,
    *,
    profile: str | None = None,
    chrome_root: Path = DEFAULT_CHROME_ROOT,
    extract: CookieExtractor = extract_chrome_cookies,
    now: float | None = None,
) -> ChromeLogin:
    """Return the one Chrome profile logged in to ``target``; never guess."""
    current = time.time() if now is None else now
    try:
        available = chrome_profiles(chrome_root=chrome_root)
    except FileNotFoundError:
        raise ChromeSourceError(
            ExitCode.ACTION_REQUIRED, "chrome_missing", "本机没有找到 Chrome 数据目录。"
        ) from None
    except OSError as exc:
        raise _folder_denied() from exc
    if profile is not None:
        available = tuple(item for item in available if item.directory == profile)
        if not available:
            raise ChromeSourceError(
                ExitCode.ACTION_REQUIRED,
                "chrome_profile_missing",
                f"Chrome 中不存在 Profile「{profile}」。",
            )
    candidates: list[ChromeLogin] = []
    denied = False
    for item in available:
        try:
            jar = extract(
                tuple(sorted(target.cookie_domains)),
                item.directory,
                chrome_root=chrome_root,
            )
        except FileNotFoundError:
            continue
        except PermissionError:
            denied = True
            continue
        except OSError as exc:
            raise ChromeSourceError(
                ExitCode.UNAVAILABLE, "chrome_unavailable", f"无法读取 Chrome：{exc}"
            ) from None
        cookies = _live_cookies(jar, target, current)
        if cookies:
            candidates.append(ChromeLogin(item, cookies))
    if len(candidates) > 1:
        listed = "、".join(_label(choice.profile) for choice in candidates)
        raise ChromeSourceError(
            ExitCode.ACTION_REQUIRED,
            "chrome_profile_ambiguous",
            f"多个 Chrome Profile 都登录了 {target.site}：{listed}。"
            "请在 SITE_SESSION_SOURCE_PROFILES 中指定一个。",
        )
    if denied:
        raise _keychain_denied()
    if not candidates:
        scope = f"Profile「{profile}」" if profile else "任何 Chrome Profile"
        raise ChromeSourceError(
            ExitCode.ACTION_REQUIRED,
            "credential_required",
            f"{scope} 中没有 {target.site} 的有效登录状态，请先在 Chrome 中登录。",
        )
    return candidates[0]


class CookiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    site: Annotated[str, StringConstraints(pattern=r"^[a-z0-9.-]{3,253}$")]
    public_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    # Page-signed headers are per request; only a lease asks for them.
    include_headers: bool = False


class CookiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    site: str
    profile: str
    jar: str
    headers: str | None = None


def cookies_associated_data(site: str) -> bytes:
    return f"chrome-agent-cookies:v1:{site}".encode()


def headers_associated_data(site: str) -> bytes:
    return f"chrome-agent-headers:v1:{site}".encode()


type LoginReader = Callable[[SiteTarget, str | None], ChromeLogin]
type HeaderReader = Callable[
    [SiteSessionPolicy, tuple[Cookie, ...]], Awaitable[bytes | None]
]


def create_app(
    *,
    secret: bytes,
    profiles: Mapping[str, str],
    reader: LoginReader | None = None,
    header_reader: HeaderReader = page_headers,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    verifier = authenticator(secret)
    read = reader or (lambda target, profile: read_login(target, profile=profile))
    cache: dict[str, tuple[float, ChromeLogin]] = {}
    lock = asyncio.Lock()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    async def login_for(target: SiteTarget) -> ChromeLogin:
        async with lock:
            hit = cache.get(target.site)
            if hit is not None and clock() - hit[0] < _CACHE_SECONDS:
                return hit[1]
            login = await asyncio.to_thread(read, target, profiles.get(target.site))
            cache[target.site] = (clock(), login)
            return login

    @app.post(COOKIES_PATH, response_model=CookiesResponse)
    async def cookies(request: Request) -> CookiesResponse:
        body = await verified_model(request, verifier, CookiesRequest)
        try:
            target = site_target(body.site)
            recipient = decode_public_key(body.public_key)
        except (InvalidSessionSite, SealError, ValueError):
            raise HTTPException(422, "invalid_request") from None
        try:
            login = await login_for(target)
        except ChromeSourceError as exc:
            status = {
                ExitCode.PERMISSION_DENIED: 403,
                ExitCode.UNAVAILABLE: 503,
            }.get(exc.code, 409)
            raise HTTPException(status, exc.reason) from None
        headers = None
        if body.include_headers:
            try:
                raw = await header_reader(target.policy, login.cookies)
            except PageHeadersUnavailable:
                raise HTTPException(409, "credential_required") from None
            except Exception:
                raise HTTPException(503, "page_headers_unavailable") from None
            if raw is not None:
                headers = encode(
                    seal(
                        raw,
                        recipient,
                        associated_data=headers_associated_data(target.site),
                    )
                )
        payload = serialize_cookies(login.cookies)
        sealed = seal(
            payload, recipient, associated_data=cookies_associated_data(target.site)
        )
        return CookiesResponse(
            site=target.site,
            profile=login.profile.directory,
            jar=encode(sealed),
            headers=headers,
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


@dataclass(frozen=True, slots=True)
class AgentConfig:
    secret: bytes
    profiles: dict[str, str]
    sites: tuple[str, ...]


def load_config(env_file: Path) -> AgentConfig:
    values = {k: v for k, v in dotenv_values(env_file).items() if v is not None}
    values.update(
        {k: v for k, v in os.environ.items() if k.startswith("SITE_SESSION_")}
    )
    secret = values.get("SITE_SESSION_AGENT_SECRET") or (
        "development-site-session-agent-secret-change-me"
    )
    if len(secret.encode()) < 32:
        raise SystemExit("SITE_SESSION_AGENT_SECRET must contain at least 32 bytes")
    profiles = json.loads(values.get("SITE_SESSION_SOURCE_PROFILES") or "{}")
    sites = json.loads(values.get("SITE_SESSION_SOURCE_SITES") or "null") or list(
        known_session_sites()
    )
    known = set(known_session_sites())
    if set(sites) - known or set(profiles) - known:
        raise SystemExit("SITE_SESSION_SOURCE_* may only name registered sites")
    if any(_PROFILE_NAME.fullmatch(name) is None for name in profiles.values()):
        raise SystemExit("SITE_SESSION_SOURCE_PROFILES must name Chrome profile dirs")
    return AgentConfig(secret.encode(), dict(profiles), tuple(sites))


def agent_spec(env_file: Path) -> dict[str, object]:
    return {
        "Label": AGENT_LABEL,
        "ProgramArguments": [
            sys.executable,
            "-m",
            "app.workers.session.chrome_agent",
            "serve",
            "--env-file",
            str(env_file),
        ],
        "WorkingDirectory": str(PROJECT_ROOT / "backend"),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "ProcessType": "Background",
        "Umask": 0o077,
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    }


def _launchctl(*args: str, check: bool = True) -> None:
    subprocess.run(
        ["/bin/launchctl", *args],
        check=check,
        timeout=15,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _plist() -> Path:
    return Path.home() / "Library/LaunchAgents" / f"{AGENT_LABEL}.plist"


def install(env_file: Path) -> None:
    destination = _plist()
    destination.parent.mkdir(parents=True, exist_ok=True)
    _launchctl("bootout", f"gui/{os.getuid()}/{AGENT_LABEL}", check=False)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
        stream.write(plistlib.dumps(agent_spec(env_file)))
        temporary = Path(stream.name)
    temporary.replace(destination)
    _launchctl("bootstrap", f"gui/{os.getuid()}", str(destination))


def uninstall() -> None:
    _launchctl("bootout", f"gui/{os.getuid()}/{AGENT_LABEL}", check=False)
    _plist().unlink(missing_ok=True)


def check(config: AgentConfig) -> int:
    """Read every configured site once, exactly like the agent would."""
    print(f"读取程序：{Path(sys.executable).resolve()}")
    worst = ExitCode.OK
    for site in config.sites:
        try:
            login = read_login(site_target(site), profile=config.profiles.get(site))
            count = len(login.cookies)
            print(f"{site}\t已登录\t{_label(login.profile)}\t{count} 个 Cookie")
        except ChromeSourceError as exc:
            print(f"{site}\t{exc.reason}\t{exc}")
            worst = max(worst, exc.code)
    return int(worst)


def _live_cookies(jar: CookieJar, target: SiteTarget, now: float) -> tuple[Cookie, ...]:
    cookies = tuple(
        cookie
        for cookie in jar
        if cookie.value
        and has_safe_cookie_fields(cookie)
        and is_allowed_domain(cookie.domain, target.cookie_domains)
        and (cookie.expires is None or cookie.expires > now)
    )
    names = frozenset(cookie.name for cookie in cookies)
    persistent = any(cookie.expires is not None for cookie in cookies)
    return cookies if persistent and target.policy.accepts(names) else ()


def _folder_denied() -> ChromeSourceError:
    return ChromeSourceError(
        ExitCode.PERMISSION_DENIED,
        "chrome_permission_required",
        "macOS 拒绝访问 Chrome 数据目录。请在“系统设置 → 隐私与安全性 → "
        f"完全磁盘访问权限”中添加 {Path(sys.executable).resolve()}。",
    )


def _keychain_denied() -> ChromeSourceError:
    return ChromeSourceError(
        ExitCode.PERMISSION_DENIED,
        "chrome_permission_required",
        "macOS 拒绝读取“Chrome Safe Storage”钥匙串。请在钥匙串弹窗中选择"
        "“始终允许”，然后重试。",
    )


def _label(profile: ChromeProfile) -> str:
    if profile.display_name == profile.directory:
        return profile.directory
    return f"{profile.directory}（{profile.display_name}）"


def main() -> int:
    parser = argparse.ArgumentParser(description="本机 Chrome 登录态服务")
    parser.add_argument(
        "command",
        choices=("serve", "install", "uninstall", "check"),
        nargs="?",
        default="serve",
    )
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    args = parser.parse_args()
    env_file = args.env_file.resolve()
    if args.command == "uninstall":
        uninstall()
        print("已移除 Chrome 登录态服务。")
        return 0
    if sys.platform != "darwin":
        print("Chrome 登录态服务需要在装有 Chrome 的 macOS 上运行。")
        return 2
    config = load_config(env_file)
    if args.command == "check":
        return check(config)
    if args.command == "install":
        install(env_file)
        print("已安装并启动 Chrome 登录态服务（开机自启、崩溃自动重启）。")
        return check(config)
    uvicorn.run(
        create_app(secret=config.secret, profiles=config.profiles),
        host="127.0.0.1",
        port=AGENT_PORT,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
