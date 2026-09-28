"""Host import of logged-in site sessions from local Chrome.

This is the source boundary of the site session lifecycle: it
reads one site's Cookies from a Chrome profile, encrypts them and records a new
import in PostgreSQL. The container session browser takes over from there.

    uv run python -m app.workers.session.seed import --site youtube.com
    uv run python -m app.workers.session.seed status
    uv run python -m app.workers.session.seed revoke --site youtube.com
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import IntEnum
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from typing import Any, cast

from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.core.security.site_session_cipher import SiteSessionCipher
from app.integrations.site_session_catalog import SiteTarget, site_target_for_host
from app.repositories.providers.site_sessions import (
    SiteSessionConflict,
    SiteSessionSecrets,
    SiteSessionStates,
)
from app.services.site_sessions import (
    InvalidSessionSite,
    SiteSessionState,
    SiteSessionStatus,
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
from dotenv import dotenv_values
from sqlalchemy.exc import SQLAlchemyError

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_EGRESS_ROUTE = "default"


class ExitCode(IntEnum):
    OK = 0
    ACTION_REQUIRED = 2
    PERMISSION_DENIED = 3
    UNAVAILABLE = 4


class SeedError(Exception):
    def __init__(self, code: ExitCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SeedChoice:
    profile: ChromeProfile
    cookies: tuple[Cookie, ...]


type CookieExtractor = Callable[..., CookieJar]


def select_seed(
    target: SiteTarget,
    *,
    profile: str | None = None,
    chrome_root: Path = DEFAULT_CHROME_ROOT,
    extract: CookieExtractor = extract_chrome_cookies,
    now: float | None = None,
) -> SeedChoice:
    """Pick exactly one logged-in profile; never guess between accounts."""
    current = time.time() if now is None else now
    try:
        available = chrome_profiles(chrome_root=chrome_root)
    except FileNotFoundError:
        raise SeedError(
            ExitCode.ACTION_REQUIRED, "本机没有找到 Chrome 数据目录。"
        ) from None
    except OSError as exc:
        raise _folder_denied() from exc
    if profile is not None:
        available = tuple(item for item in available if item.directory == profile)
        if not available:
            raise SeedError(
                ExitCode.ACTION_REQUIRED, f"Chrome 中不存在 Profile「{profile}」。"
            )
    candidates: list[SeedChoice] = []
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
            raise SeedError(ExitCode.UNAVAILABLE, f"无法读取 Chrome：{exc}") from None
        cookies = _live_cookies(jar, target, current)
        if cookies:
            candidates.append(SeedChoice(item, cookies))
    if len(candidates) > 1:
        listed = "、".join(_label(choice.profile) for choice in candidates)
        raise SeedError(
            ExitCode.ACTION_REQUIRED,
            f"多个 Chrome Profile 都登录了 {target.site}：{listed}。"
            "请用 --profile 指定要导入的账号。",
        )
    if denied:
        raise _keychain_denied()
    if not candidates:
        scope = f"Profile「{profile}」" if profile else "任何 Chrome Profile"
        raise SeedError(
            ExitCode.ACTION_REQUIRED,
            f"{scope} 中没有 {target.site} 的有效登录状态，请先在 Chrome 中登录。",
        )
    return candidates[0]


async def import_session(
    target: SiteTarget,
    choice: SeedChoice,
    *,
    states: SiteSessionStates,
    secrets: SiteSessionSecrets,
    cipher: SiteSessionCipher,
    egress_route: str = DEFAULT_EGRESS_ROUTE,
    automatic: bool = False,
    expected_seed_revision: int | None = None,
) -> int:
    current = await states.get(target.site)
    expected = 0 if current is None else current.seed_revision
    if expected_seed_revision is not None and expected != expected_seed_revision:
        raise SiteSessionConflict("site session changed")
    payload = serialize_cookies(choice.cookies)
    ciphertext = cipher.encrypt(target.site, expected + 1, 0, payload)
    return await secrets.seed(
        target.site,
        provider_key=(
            None
            if target.policy.provider_key is None
            else target.policy.provider_key.value
        ),
        expected_seed_revision=expected,
        ciphertext=ciphertext,
        egress_route=egress_route,
        source_profile=choice.profile.directory,
        source_fingerprint=source_fingerprint(target, choice, cipher),
        automatic=automatic,
    )


def source_fingerprint(
    target: SiteTarget, choice: SeedChoice, cipher: SiteSessionCipher
) -> str:
    # Ignore tracking values and expiry extension; only new authentication
    # material justifies trying a rejected source again.
    auth = sorted(
        (c.domain, c.path, c.name, c.value)
        for c in choice.cookies
        if c.name in target.policy.required_cookie_names
    )
    return cipher.source_fingerprint(target.site, json.dumps(auth).encode())


async def revoke_session(
    site: str, *, states: SiteSessionStates, secrets: SiteSessionSecrets
) -> SiteSessionStatus:
    current = await states.get(site)
    if current is None or current.state is SiteSessionState.REVOKED:
        raise SeedError(ExitCode.ACTION_REQUIRED, f"{site} 没有可撤销的会话。")
    await secrets.revoke(site, expected_seed_revision=current.seed_revision)
    return current


def load_settings(env_file: Path) -> Settings:
    values = {
        key.lower(): value
        for key, value in dotenv_values(env_file).items()
        if value is not None
    }
    fields = (
        "database_url",
        "site_session_encryption_key",
        "site_session_source_sites",
        "site_session_source_profiles",
        "site_session_source_interval_seconds",
    )
    for field in fields:
        key = field.upper()
        if key in os.environ:
            values[key.lower()] = os.environ[key]
    required = {key: values[key] for key in fields if values.get(key)}
    for field in ("site_session_source_sites", "site_session_source_profiles"):
        if field in required:
            required[field] = json.loads(required[field])
    return Settings(
        _env_file=None,
        service_role="provider-sources",
        **cast(dict[str, Any], required),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except SeedError as exc:
        print(exc, file=sys.stderr)
        return int(exc.code)


async def _run(args: argparse.Namespace) -> int:
    target = None
    if args.command in {"import", "revoke"}:
        try:
            target = site_target_for_host(args.site)
        except InvalidSessionSite:
            raise SeedError(
                ExitCode.ACTION_REQUIRED,
                f"不能为「{args.site}」登记会话：必须是公网域名，"
                "不能是 IP、内网名称或公共后缀（如 co.uk、github.io）。",
            ) from None
    choice = None
    if args.command == "import":
        assert target is not None
        # Read Chrome before touching the database so a keychain prompt is the
        # first thing the operator sees.
        choice = await asyncio.to_thread(select_seed, target, profile=args.profile)
    settings = load_settings(args.env_file.absolute())
    key = settings.site_session_encryption_key
    if key is None and args.command == "import":
        raise SeedError(
            ExitCode.ACTION_REQUIRED,
            "未配置 SITE_SESSION_ENCRYPTION_KEY；"
            "请在部署环境文件中设置稳定的 Fernet 密钥。",
        )
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    states, secrets = SiteSessionStates(sessions), SiteSessionSecrets(sessions)
    try:
        if args.command == "status":
            _print_status(await states.list())
        elif args.command == "import":
            assert target is not None and choice is not None and key is not None
            revision = await import_session(
                target,
                choice,
                states=states,
                secrets=secrets,
                cipher=SiteSessionCipher(key.get_secret_value()),
            )
            print(
                f"{target.site}：已从 Chrome「{_label(choice.profile)}」导入 "
                f"{len(choice.cookies)} 个 Cookie，修订 {revision}。"
                "容器会话服务将接管并验证。"
            )
        else:
            assert target is not None
            revoked = await revoke_session(target.site, states=states, secrets=secrets)
            print(
                f"{target.site}：已撤销修订 {revoked.seed_revision}，"
                "新任务不再使用该会话。"
            )
    except SiteSessionConflict:
        raise SeedError(
            ExitCode.UNAVAILABLE, "会话记录刚被其他操作更新，请重新执行。"
        ) from None
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        raise SeedError(
            ExitCode.UNAVAILABLE, f"数据库不可用：{type(exc).__name__}"
        ) from None
    finally:
        await engine.dispose()
    return ExitCode.OK


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


def _folder_denied() -> SeedError:
    # macOS privacy protection: only Chrome and apps granted Full Disk Access
    # may open Chrome's data folder.
    return SeedError(
        ExitCode.PERMISSION_DENIED,
        "macOS 拒绝访问 Chrome 数据目录。请在“系统设置 → 隐私与安全性 → "
        "完全磁盘访问权限”中允许运行本命令的应用（终端或 Claude），然后重试。",
    )


def _keychain_denied() -> SeedError:
    return SeedError(
        ExitCode.PERMISSION_DENIED,
        "macOS 拒绝读取“Chrome Safe Storage”钥匙串。请在钥匙串弹窗中选择"
        "“始终允许”，然后重试。",
    )


def _label(profile: ChromeProfile) -> str:
    if profile.display_name == profile.directory:
        return profile.directory
    return f"{profile.directory}（{profile.display_name}）"


def _print_status(statuses: tuple[SiteSessionStatus, ...]) -> None:
    if not statuses:
        print("尚未登记任何站点会话。")
        return
    for status in statuses:
        refreshed = status.refreshed_at.isoformat() if status.refreshed_at else "-"
        verified = status.verified_at.isoformat() if status.verified_at else "-"
        print(
            f"{status.site}\t{status.state.value}\t修订 {status.seed_revision}"
            f"\tjar {status.jar_version}\t刷新 {refreshed}\t验证 {verified}"
            f"\t{status.last_error_code or '-'}"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="一次性导入、查看或撤销站点会话")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    commands = parser.add_subparsers(dest="command", required=True)
    imported = commands.add_parser("import", help="从本机 Chrome 导入站点登录状态")
    imported.add_argument(
        "--site", required=True, help="站点或链接主机，例如 youtube.com"
    )
    imported.add_argument("--profile", help="Chrome Profile 目录名，例如 'Profile 2'")
    commands.add_parser("status", help="列出站点会话状态")
    revoked = commands.add_parser("revoke", help="撤销站点会话")
    revoked.add_argument("--site", required=True)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
