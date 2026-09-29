"""Task-scoped access to the running Chrome through its native messaging port.

No browser database reads, persistent cookie copies, or background account probes.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from http.cookiejar import Cookie
from typing import Any

from app.integrations.site_session_catalog import known_session_sites, site_target
from app.services.site_sessions import HeaderPlugin
from app.workers.runner.netscape_cookie import (
    has_safe_cookie_fields,
    is_allowed_domain,
    serialize_cookies,
)
from app.workers.session.page_headers import yuanbao_payload
from pydantic import BaseModel, ConfigDict, Field

CONNECT_PATH = "/internal/browser/connect"
DISCONNECT_PATH = "/internal/browser/disconnect"
POLL_PATH = "/internal/browser/poll"
REPLY_PATH = "/internal/browser/reply"


class SourceUnavailable(Exception):
    def __init__(self, code: str = "provider_session_not_ready") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    site: str
    generation: int
    cookies: bytes = field(repr=False)
    headers: bytes | None = field(default=None, repr=False)


class BrowserConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection: str = Field(min_length=32, max_length=64)


class BrowserReply(BrowserConnection):
    request_id: str = Field(min_length=32, max_length=64)
    cookies: list[dict[str, Any]] = Field(
        default_factory=list, max_length=500, repr=False
    )
    auth: dict[str, Any] | None = Field(default=None, repr=False)
    error: str | None = Field(default=None, max_length=64)


class ChromeSource:
    def __init__(self, *, secret: bytes) -> None:
        self._secret = secret
        self._instance = secrets.token_bytes(32)
        self._connection: str | None = None
        self._heartbeat = 0.0
        self._commands: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=16)
        self._pending: dict[str, asyncio.Future[BrowserReply]] = {}
        self._locks = {site: asyncio.Lock() for site in known_session_sites()}

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        self._connection = None
        self._invalidate()

    def _invalidate(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(SourceUnavailable())
        while not self._commands.empty():
            self._commands.get_nowait()

    def disconnect(self, connection: str) -> None:
        self._verify(connection)
        self._connection = None
        self._invalidate()

    def connect(self) -> BrowserConnection:
        if self._connection is not None and time.monotonic() - self._heartbeat < 45:
            raise SourceUnavailable()
        self._invalidate()
        self._connection = secrets.token_urlsafe(32)
        self._heartbeat = time.monotonic()
        return BrowserConnection(connection=self._connection)

    def _verify(self, connection: str) -> None:
        if connection != self._connection:
            raise SourceUnavailable("credential_revoked")
        self._heartbeat = time.monotonic()

    async def poll(self, connection: str) -> dict[str, Any]:
        self._verify(connection)
        try:
            async with asyncio.timeout(20):
                while True:
                    command = await self._commands.get()
                    if command["request_id"] in self._pending:
                        self._verify(connection)
                        return command
        except TimeoutError:
            self._verify(connection)
            return {"command": "idle"}

    def reply(self, reply: BrowserReply) -> None:
        self._verify(reply.connection)
        future = self._pending.get(reply.request_id)
        if future is None or future.done():
            raise SourceUnavailable("credential_revoked")
        future.set_result(reply)

    def _site(self, site: str) -> None:
        if site not in self._locks:
            raise SourceUnavailable("provider_session_not_allowed")

    async def _request(
        self, site: str, command: str, *, include_headers: bool = False
    ) -> BrowserReply:
        self._site(site)
        if self._connection is None or time.monotonic() - self._heartbeat > 45:
            raise SourceUnavailable()
        target = site_target(site)
        request_id = secrets.token_urlsafe(32)
        future: asyncio.Future[BrowserReply] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[request_id] = future
        try:
            self._commands.put_nowait(
                {
                    "command": command,
                    "request_id": request_id,
                    "site": site,
                    "domains": sorted(target.cookie_domains),
                    "login_url": target.policy.login_url,
                    "header_plugin": str(target.policy.header_plugin)
                    if include_headers and target.policy.header_plugin
                    else None,
                }
            )
            async with asyncio.timeout(35):
                reply = await future
            self._verify(reply.connection)
            if reply.error:
                raise SourceUnavailable(
                    "credential_required"
                    if reply.error == "credential_required"
                    else "provider_session_not_ready"
                )
            return reply
        except (TimeoutError, asyncio.QueueFull):
            raise SourceUnavailable() from None
        finally:
            self._pending.pop(request_id, None)
            future.cancel()

    async def read(self, site: str, *, include_headers: bool = False) -> SourceSnapshot:
        self._site(site)
        async with self._locks[site]:
            reply = await self._request(site, "read", include_headers=include_headers)
            target = site_target(site)
            cookies = []
            try:
                for value in reply.cookies:
                    if not is_allowed_domain(value["domain"], target.cookie_domains):
                        continue
                    item = _cookie(value)
                    if (
                        item.value
                        and (item.expires is None or item.expires > time.time())
                        and has_safe_cookie_fields(item)
                    ):
                        cookies.append(item)
                if not target.policy.accepts(frozenset(c.name for c in cookies)):
                    raise SourceUnavailable("credential_required")
                headers = (
                    yuanbao_payload(reply.auth, cookies)
                    if include_headers
                    and target.policy.header_plugin is HeaderPlugin.YUANBAO
                    else None
                )
                identity = sorted(
                    (c.domain, c.path, c.name, c.value)
                    for c in cookies
                    if not target.policy.required_cookie_names
                    or c.name in target.policy.required_cookie_names
                )
                digest = hmac.digest(
                    self._secret,
                    self._instance
                    + (self._connection or "").encode()
                    + site.encode()
                    + json.dumps(identity, separators=(",", ":")).encode(),
                    hashlib.sha256,
                )
                return SourceSnapshot(
                    site,
                    int.from_bytes(digest[:16], "big") + 1,
                    serialize_cookies(cookies),
                    headers,
                )
            except SourceUnavailable:
                raise
            except Exception:
                raise SourceUnavailable() from None

    async def open_login(self, site: str) -> None:
        await self._request(site, "login")

    async def finish_login(self, site: str) -> None:
        self._site(site)


def _cookie(item: dict[str, Any]) -> Cookie:
    expiry = item.get("expirationDate")
    expires = int(expiry) if isinstance(expiry, (float, int)) and expiry > 0 else None
    return Cookie(
        0,
        item["name"],
        item["value"],
        None,
        False,
        item["domain"],
        True,
        item["domain"].startswith("."),
        item["path"],
        True,
        item["secure"],
        expires,
        expires is None,
        None,
        None,
        {"HttpOnly": ""} if item.get("httpOnly") else {},
    )
