"""Authenticated Chrome bridge. Identity material is operation-local only."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from urllib.parse import unquote

from app.core.config import CookieSourceSettings
from app.workers.identity.extension import extension_origin
from app.workers.identity.yuanbao_account import (
    YUANBAO_ORIGIN,
    YuanbaoAccountMaterial,
    stable_yuanbao_account_digest,
    validate_yuanbao_account_payload,
)
from app.workers.runner.netscape_cookie import (
    MAX_COOKIE_BYTES,
    is_allowed_domain,
    parse_cookie_payload,
)
from app.workers.runner.provider_registry import provider_profile_for_key
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
)

# Audited 2026-10-01. Each inner set is an AND group; groups are alternatives.
# This is a necessary-material gate, not a claim that the account is still valid.
# Fingerprints bind only account material, not volatile visitor/proof cookies.
_ACCOUNT_COOKIES: dict[
    str, tuple[tuple[frozenset[str], ...], frozenset[str]] | None
] = {
    # yt-dlp/extractor/youtube/_base.py: is_authenticated + _get_sid_cookies.
    # https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_base.py
    # LOGIN_INFO prevents stale SAPISID variants from being mistaken for login.
    "youtube": (
        tuple(
            frozenset({"LOGIN_INFO", sid})
            for sid in ("SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID")
        ),
        frozenset(
            {
                "LOGIN_INFO",
                "SAPISID",
                "__Secure-1PAPISID",
                "__Secure-3PAPISID",
                "__Secure-1PSID",
                "__Secure-3PSID",
                "SID",
            }
        ),
    ),
    # https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/bilibili.py
    # BilibiliBaseIE.is_logged_in checks SESSDATA at api.bilibili.com.
    "bilibili": ((frozenset({"SESSDATA"}),), frozenset({"SESSDATA", "DedeUserID"})),
    # https://github.com/jiji262/douyin-downloader/blob/main/core/api_client.py
    # _has_login_session_cookie accepts sessionid/sessionid_ss (not msToken).
    "douyin": (
        (frozenset({"sessionid"}), frozenset({"sessionid_ss"})),
        frozenset(
            {"sessionid", "sessionid_ss", "sid_tt", "sid_guard", "uid_tt", "uid_tt_ss"}
        ),
    ),
    # https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/xhs/login.py
    # check_login_state uses web_session; visitor a1/webId alone are insufficient.
    "xiaohongshu": ((frozenset({"web_session"}),), frozenset({"web_session"})),
    # https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/kuaishou/login.py
    # check_login_state requires passToken. Web session pair used by the PC client:
    # https://github.com/sonderlau/KuaiShouVideoDownload/blob/main/README_EN.md
    "kuaishou": (
        (
            frozenset({"passToken"}),
            frozenset({"kuaishou.server.web_st", "kuaishou.server.web_ph"}),
        ),
        frozenset(
            {"passToken", "userId", "kuaishou.server.web_st", "kuaishou.server.web_ph"}
        ),
    ),
    # https://github.com/tamnd/weibo-cli/blob/main/README.md#getting-a-session-cookie
    # SUB is the session credential; SUBP/WBPSESS bind related account state.
    "weibo": ((frozenset({"SUB"}),), frozenset({"SUB", "SUBP", "WBPSESS"})),
    # https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/twitter.py
    # is_logged_in checks auth_token, _set_base_headers reads ct0 for CSRF.
    "x": ((frozenset({"auth_token", "ct0"}),), frozenset({"auth_token", "ct0"})),
    # https://github.com/0xEnc0der/fbcli#accepted-cookie-formats-auto-detected
    # Both authentication cookies are needed; datr/sb alone identify a browser.
    "facebook": ((frozenset({"c_user", "xs"}),), frozenset({"c_user", "xs"})),
    # Upstream RedditIE._is_logged_in checks reddit_session, not visitor loid:
    # https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/reddit.py
    "reddit": ((frozenset({"reddit_session"}),), frozenset({"reddit_session"})),
    # https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/instagram.py
    # InstagramBaseIE._AUTH_COOKIE_NAME/is_logged_in.
    "instagram": (
        (frozenset({"sessionid"}),),
        frozenset({"sessionid", "csrftoken", "ds_user_id"}),
    ),
    # Current in-repo yt-dlp plugin personal_video.py, QQPersonalIE._real_extract:
    # login_token maps vuserid/vusession directly to these two Cookie names.
    "qqvideo": (
        (frozenset({"v_vuserid", "v_vusession"}),),
        frozenset(
            {
                "v_vuserid",
                "v_vusession",
                "v_main_login",
                "v_t_openid",
                "v_t_appid",
                "v_t_access_token",
            }
        ),
    ),
    # The official policy groups P_pck_rm/P_gck with login/account material;
    # the current Chinese PC client uses P_gck's second field as account marker:
    # https://terms.alicdn.com/legal-agreement/terms/c_platform_service_agreement/20230407105056824/20230407105056824.html
    # https://g.alicdn.com/youku-node/pc-pages-v2/4.1.871/v2/static/js/vendors.chunk.js
    # A persistent ticket needs that non-visitor marker; neither alone proves login.
    # Current plugin personal_video.py passes the Cookie jar to the official UPS.
    "youku": (
        (frozenset({"P_sck"}), frozenset({"P_pck_rm", "P_gck"})),
        frozenset({"P_sck", "P_pck", "P_pck_rm", "P_gck"}),
    ),
}
AUTH_TIMEOUT = 5.0
REQUEST_TIMEOUT = 5.0
HEARTBEAT_SECONDS = 20.0
MAX_CONNECTIONS = 2  # includes the active connection and one bounded handshake
MAX_REQUESTS = 1
YUANBAO_READ_CAUSES = frozenset(
    {
        "credential_missing",
        "identity_material_invalid",
        "identity_origin_invalid",
        "identity_navigation_changed",
        "identity_account_conflict",
        "identity_tab_ambiguous",
        "identity_page_unavailable",
        "identity_storage_unavailable",
        "extension_timeout",
    }
)


class IdentityUnavailable(Exception):
    def __init__(self, cause: str):
        super().__init__(cause)
        self.cause = cause


class CookieRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    site: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    task_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    deadline: AwareDatetime


class ExtensionCookie(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    domain: str = Field(pattern=r"^\.?[A-Za-z0-9.-]{1,253}$")
    path: str = Field(pattern=r"^/[^\t\r\n\x00]*$", max_length=4096)
    name: str = Field(pattern=r"^[^\t\r\n\x00]*$", max_length=4096)
    value: str = Field(pattern=r"^[^\t\r\n\x00]*$", max_length=65536)
    secure: StrictBool
    httpOnly: StrictBool
    hostOnly: StrictBool
    expirationDate: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    def line(self) -> str:
        domain = self.domain if self.hostOnly else "." + self.domain.lstrip(".")
        if self.httpOnly:
            domain = "#HttpOnly_" + domain
        return "\t".join(
            (
                domain,
                "FALSE" if self.hostOnly else "TRUE",
                self.path,
                "TRUE" if self.secure else "FALSE",
                str(int(self.expirationDate or 0)),
                self.name,
                self.value,
            )
        )


def _youku_has_account_marker(cookies: list[ExtensionCookie]) -> bool:
    """Allow native account validation, never treat a visitor marker as login."""
    for cookie in cookies:
        if cookie.name != "P_gck" or re.search(r"%(?![0-9a-fA-F]{2})", cookie.value):
            continue
        try:
            fields = unquote(cookie.value, errors="strict").split("|")
        except UnicodeError:
            continue
        if len(fields) < 2:
            continue
        account = fields[1]
        if (
            account
            and account == account.strip()
            and account != "NA"
            and not any(ord(char) < 32 or ord(char) == 127 for char in account)
        ):
            return True
    return False


def proof(key: str, role: str, peer: str, own: str) -> str:
    return hmac.new(
        key.encode(), (role + peer + own).encode(), hashlib.sha256
    ).hexdigest()


async def receive(websocket: WebSocket) -> dict[str, object]:
    text = await websocket.receive_text()
    if len(text.encode()) > MAX_COOKIE_BYTES:
        raise ValueError("message_too_large")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("invalid_message")
    return value


class CookieSource:
    def __init__(self, settings: CookieSourceSettings):
        self.settings = settings
        self.connection: WebSocket | None = None
        self.version: str | None = None
        self._connections = 0
        self._pending: dict[str, asyncio.Future[object]] = {}
        self._pending_kinds: dict[str, str] = {}
        self._requests = 0
        self._send_lock = asyncio.Lock()

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close(code=1001)
        self.disconnected(self.connection)

    def disconnected(self, websocket: WebSocket | None) -> None:
        if self.connection is not websocket:
            return
        self.connection = None
        self.version = None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(IdentityUnavailable("extension_disconnected"))
        self._pending.clear()
        self._pending_kinds.clear()

    async def send(self, websocket: WebSocket, message: dict[str, object]) -> None:
        async with self._send_lock:
            await websocket.send_json(message)

    async def extension(self, websocket: WebSocket) -> None:
        if (
            websocket.headers.get("origin") != extension_origin()
            or self.connection is not None
            or self._connections >= MAX_CONNECTIONS
        ):
            await websocket.close(code=1008)
            return
        self._connections += 1
        try:
            await websocket.accept()
            async with asyncio.timeout(AUTH_TIMEOUT):
                own = secrets.token_hex(32)
                await self.send(websocket, {"type": "challenge", "nonce": own})
                challenge = await receive(websocket)
                peer = challenge.get("nonce")
                if (
                    set(challenge) != {"type", "nonce"}
                    or challenge["type"] != "challenge"
                    or not isinstance(peer, str)
                    or not re.fullmatch(r"[a-f0-9]{64}", peer)
                ):
                    raise ValueError("invalid_challenge")
                key = self.settings.cookie_source_pairing_key.get_secret_value()
                await self.send(
                    websocket,
                    {"type": "proof", "proof": proof(key, "server", peer, own)},
                )
                response = await receive(websocket)
                supplied = response.get("proof")
                version = response.get("version")
                if (
                    set(response) != {"type", "proof", "version"}
                    or response["type"] != "proof"
                    or not isinstance(supplied, str)
                    or not isinstance(version, str)
                    or not re.fullmatch(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}", version)
                    or not hmac.compare_digest(
                        supplied, proof(key, "extension", own, peer)
                    )
                ):
                    raise ValueError("authentication_failed")
                # No await between the check and assignment: simultaneous
                # handshakes cannot replace the first authenticated Profile.
                if self.connection is not None:
                    raise ValueError("already_connected")
                self.connection = websocket
                self.version = version
                await self.send(websocket, {"type": "ready"})
            async with asyncio.TaskGroup() as group:
                group.create_task(self._heartbeat(websocket))
                group.create_task(self._responses(websocket))
        except (Exception, asyncio.CancelledError):
            # Never log validation errors or messages (they can contain Cookie values).
            with suppress(Exception):
                await websocket.close(code=1008)
        finally:
            self.disconnected(websocket)
            self._connections -= 1

    async def _heartbeat(self, websocket: WebSocket) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await self.send(websocket, {"type": "ping"})

    async def _responses(self, websocket: WebSocket) -> None:
        while True:
            async with asyncio.timeout(45):
                message = await receive(websocket)
            if message == {"type": "ping"}:
                await self.send(websocket, {"type": "pong"})
            elif message == {"type": "pong"}:
                continue
            elif message.get("type") == "cookies":
                request_id = message.get("request_id")
                if not isinstance(request_id, str) or not re.fullmatch(
                    r"[a-f0-9]{32}", request_id
                ):
                    raise ValueError("invalid_response")
                if set(message) == {"type", "request_id", "cookies"}:
                    cookies = message["cookies"]
                    if not isinstance(cookies, list):
                        raise ValueError("invalid_response")
                elif (
                    set(message) == {"type", "request_id", "cause"}
                    and message["cause"] == "extension_timeout"
                ):
                    cookies = IdentityUnavailable("extension_timeout")
                else:
                    raise ValueError("invalid_response")
                future = self._pending.get(request_id)
                # Ignore only late responses to expired/cancelled requests.
                if future is not None and not future.done():
                    if self._pending_kinds.get(request_id) != "cookies":
                        raise ValueError("invalid_response")
                    if isinstance(cookies, IdentityUnavailable):
                        future.set_exception(cookies)
                    else:
                        future.set_result(cookies)
            elif message.get("type") == "yuanbao_account":
                request_id = message.get("request_id")
                if not isinstance(request_id, str) or not re.fullmatch(
                    r"[a-f0-9]{32}", request_id
                ):
                    raise ValueError("invalid_response")
                if set(message) == {"type", "request_id", "cause"}:
                    cause = message["cause"]
                    if not isinstance(cause, str) or cause not in YUANBAO_READ_CAUSES:
                        raise ValueError("invalid_response")
                    result: object = IdentityUnavailable(cause)
                elif set(message) == {
                    "type",
                    "request_id",
                    "origin",
                    "account_id",
                    "auth_token",
                }:
                    result = {
                        name: message[name]
                        for name in ("origin", "account_id", "auth_token")
                    }
                else:
                    raise ValueError("invalid_response")
                future = self._pending.get(request_id)
                if future is not None and not future.done():
                    if self._pending_kinds.get(request_id) != "yuanbao_account":
                        raise ValueError("invalid_response")
                    if isinstance(result, IdentityUnavailable):
                        future.set_exception(result)
                    else:
                        future.set_result(result)
            else:
                raise ValueError("invalid_response")
            # Do not keep a delivered account payload in the idle receive loop.
            message = {}
            future = None
            result = None
            cookies = None

    async def cookies(self, request: CookieRequest) -> dict[str, str]:
        remaining = (request.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise IdentityUnavailable("identity_deadline_invalid")
        profile = provider_profile_for_key(request.site)
        if profile.identity_source != "cookies":
            raise IdentityUnavailable("identity_source_mismatch")
        if not profile.cookie_domain_allowlist or profile.identity == "none":
            raise IdentityUnavailable("identity_not_declared")
        if self.connection is None:
            raise IdentityUnavailable("extension_disconnected")
        rule = _ACCOUNT_COOKIES.get(request.site)
        if rule is None:
            raise IdentityUnavailable("identity_cookie_rules_unverified")
        if self._requests >= MAX_REQUESTS:
            raise IdentityUnavailable("extension_timeout")
        self._requests += 1
        request_id = secrets.token_hex(16)
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        self._pending_kinds[request_id] = "cookies"
        try:
            async with asyncio.timeout(min(REQUEST_TIMEOUT, remaining)):
                try:
                    await self.send(
                        self.connection,
                        {
                            "type": "cookies",
                            "request_id": request_id,
                            "domains": sorted(profile.cookie_domain_allowlist),
                            "deadline": request.deadline.astimezone(UTC).isoformat(),
                        },
                    )
                except (WebSocketDisconnect, RuntimeError):
                    raise IdentityUnavailable("extension_disconnected") from None
                items = await future
                if datetime.now(UTC) >= request.deadline:
                    raise IdentityUnavailable("identity_deadline_invalid")
                if not isinstance(items, list):
                    raise IdentityUnavailable("identity_cookie_structure_invalid")
                now = time.time()
                try:
                    selected = [ExtensionCookie.model_validate(item) for item in items]
                except ValidationError as error:
                    # Only fixed field names escape; never input, message or context.
                    fields = {
                        entry["loc"][0] for entry in error.errors() if entry["loc"]
                    }
                    field = next(
                        (
                            name
                            for name in (
                                "domain",
                                "path",
                                "name",
                                "value",
                                "expirationDate",
                                "secure",
                                "httpOnly",
                                "hostOnly",
                            )
                            if name in fields
                        ),
                        None,
                    )
                    cause = {
                        "domain": "identity_cookie_domain_invalid",
                        "path": "identity_cookie_path_invalid",
                        "name": "identity_cookie_name_invalid",
                        "value": "identity_cookie_value_invalid",
                        "expirationDate": "identity_cookie_expiry_invalid",
                        "secure": "identity_cookie_flags_invalid",
                        "httpOnly": "identity_cookie_flags_invalid",
                        "hostOnly": "identity_cookie_flags_invalid",
                    }.get(field or "", "identity_cookie_structure_invalid")
                    if any(
                        entry["type"] == "string_unicode" for entry in error.errors()
                    ):
                        cause = "identity_cookie_encoding_invalid"
                    raise IdentityUnavailable(cause) from None
                selected = [
                    c
                    for c in selected
                    if c.value and (c.expirationDate is None or c.expirationDate > now)
                ]
                if not selected:
                    raise IdentityUnavailable("credential_missing")
                if any(
                    not is_allowed_domain(
                        cookie.domain, profile.cookie_domain_allowlist
                    )
                    for cookie in selected
                ):
                    raise IdentityUnavailable("identity_cookie_domain_invalid")
                try:
                    payload = (
                        "# Netscape HTTP Cookie File\n"
                        + "\n".join(c.line() for c in selected)
                        + "\n"
                    ).encode("utf-8")
                except UnicodeEncodeError:
                    raise IdentityUnavailable(
                        "identity_cookie_encoding_invalid"
                    ) from None
                try:
                    lines = parse_cookie_payload(
                        payload, profile.cookie_domain_allowlist
                    )
                except Exception:
                    raise IdentityUnavailable(
                        "identity_cookie_payload_invalid"
                    ) from None
                alternatives, necessary = rule
                names = {line.name for line in lines}
                if not any(required <= names for required in alternatives):
                    raise IdentityUnavailable("credential_missing")
                if (
                    request.site == "youku"
                    and "P_sck" not in names
                    and not _youku_has_account_marker(selected)
                ):
                    raise IdentityUnavailable("credential_missing")
                canonical = b"\n".join(
                    sorted(
                        b"\t".join(
                            line.line.split(b"\t")[index] for index in (0, 2, 5, 6)
                        )
                        for line in lines
                        if line.name in necessary
                    )
                )
                digest = hmac.new(
                    self.settings.cookie_source_token.get_secret_value().encode(),
                    request.site.encode() + b"\x00" + canonical,
                    hashlib.sha256,
                ).hexdigest()
                result = {
                    "cookies": base64.b64encode(payload).decode("ascii"),
                    "digest": digest,
                }
                if datetime.now(UTC) >= request.deadline:
                    raise IdentityUnavailable("identity_deadline_invalid")
                return result
        except TimeoutError:
            raise IdentityUnavailable("extension_timeout") from None
        finally:
            self._pending.pop(request_id, None)
            self._pending_kinds.pop(request_id, None)
            future.cancel()
            self._requests -= 1

    async def yuanbao_account(self, request: CookieRequest) -> dict[str, str]:
        remaining = (request.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise IdentityUnavailable("identity_deadline_invalid")
        if request.site != "wechat_channels":
            raise IdentityUnavailable("identity_source_mismatch")
        profile = provider_profile_for_key(request.site)
        if (
            profile.identity_source != "yuanbao_account"
            or profile.identity_origin != YUANBAO_ORIGIN
            or profile.identity == "none"
        ):
            raise IdentityUnavailable("identity_source_mismatch")
        if self.connection is None:
            raise IdentityUnavailable("extension_disconnected")
        if self._requests >= MAX_REQUESTS:
            raise IdentityUnavailable("extension_timeout")
        self._requests += 1
        request_id = secrets.token_hex(16)
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        self._pending_kinds[request_id] = "yuanbao_account"
        try:
            async with asyncio.timeout(min(REQUEST_TIMEOUT, remaining)):
                try:
                    await self.send(
                        self.connection,
                        {
                            "type": "yuanbao_account",
                            "request_id": request_id,
                            "site": "wechat_channels",
                            "deadline": request.deadline.astimezone(UTC).isoformat(),
                        },
                    )
                except (WebSocketDisconnect, RuntimeError):
                    raise IdentityUnavailable("extension_disconnected") from None
                raw = await future
                if datetime.now(UTC) >= request.deadline:
                    raise IdentityUnavailable("identity_deadline_invalid")
                try:
                    payload = validate_yuanbao_account_payload(raw)
                except (ValidationError, ValueError, TypeError):
                    raise IdentityUnavailable("identity_material_invalid") from None
                material = YuanbaoAccountMaterial(
                    kind="yuanbao_account",
                    origin=payload.origin,
                    account_id=payload.account_id,
                    auth_token=payload.auth_token,
                    digest=stable_yuanbao_account_digest(
                        payload,
                        site=request.site,
                        key=self.settings.cookie_source_token.get_secret_value(),
                    ),
                    local_use_deadline=request.deadline.astimezone(UTC),
                )
                if datetime.now(UTC) >= request.deadline:
                    raise IdentityUnavailable("identity_deadline_invalid")
                # This authenticated private response is the sole wire export.
                # SecretStr.model_dump intentionally masks the two secret fields.
                return {
                    "kind": material.kind,
                    "origin": material.origin,
                    "account_id": material.account_id.get_secret_value(),
                    "auth_token": material.auth_token.get_secret_value(),
                    "digest": material.digest,
                    "local_use_deadline": material.local_use_deadline.isoformat(),
                }
        except TimeoutError:
            raise IdentityUnavailable("extension_timeout") from None
        finally:
            self._pending.pop(request_id, None)
            self._pending_kinds.pop(request_id, None)
            future.cancel()
            self._requests -= 1


def create_app(settings: CookieSourceSettings) -> FastAPI:
    if hmac.compare_digest(
        settings.cookie_source_token.get_secret_value(),
        settings.cookie_source_pairing_key.get_secret_value(),
    ):
        raise ValueError("pairing_key_must_differ_from_runner_token")
    source = CookieSource(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await source.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.cookie_source = source

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse({"cause": "invalid_request"}, status_code=422)

    @app.middleware("http")
    async def authenticated(request: Request, call_next):  # type: ignore[no-untyped-def]
        expected = f"Bearer {settings.cookie_source_token.get_secret_value()}".encode()
        if not hmac.compare_digest(
            request.headers.get("authorization", "").encode(), expected
        ):
            return JSONResponse(
                {"cause": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )
        if request.url.path == "/status" and request.method == "GET":
            return JSONResponse(
                {"connected": source.connection is not None, "version": source.version},
                headers={"Cache-Control": "no-store"},
            )
        if (
            request.url.path not in {"/cookies", "/yuanbao-account"}
            or request.method != "POST"
        ):
            return JSONResponse({"cause": "not_found"}, status_code=404)
        try:
            body = bytearray()
            async with asyncio.timeout(2):
                async for part in request.stream():
                    body.extend(part)
                    if len(body) > 4096:
                        return JSONResponse(
                            {"cause": "request_too_large"}, status_code=413
                        )
            request._body = bytes(body)
        except Exception:
            return JSONResponse({"cause": "invalid_request"}, status_code=400)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.websocket("/extension")
    async def extension(websocket: WebSocket) -> None:
        await source.extension(websocket)

    @app.post("/cookies")
    async def cookies(request: CookieRequest) -> JSONResponse:
        try:
            result = await source.cookies(request)
        except IdentityUnavailable as error:
            return JSONResponse({"cause": error.cause}, status_code=503)
        except Exception:
            return JSONResponse({"cause": "identity_material_invalid"}, status_code=503)
        return JSONResponse(result)

    @app.post("/yuanbao-account")
    async def yuanbao_account(request: CookieRequest) -> JSONResponse:
        try:
            result = await source.yuanbao_account(request)
        except IdentityUnavailable as error:
            return JSONResponse({"cause": error.cause}, status_code=503)
        except Exception:
            return JSONResponse({"cause": "identity_material_invalid"}, status_code=503)
        return JSONResponse(result)

    return app
