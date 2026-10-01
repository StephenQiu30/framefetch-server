"""Loopback-only, authenticated host Cookie service. No account material is logged."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import signal
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from app.core.config import CookieSourceSettings
from app.workers.identity.keychain import (
    KeychainUnavailable,
    require_unlocked,
    storage_password,
    validate_storage_acl,
)
from app.workers.runner.netscape_cookie import MAX_COOKIE_BYTES, parse_cookie_payload
from app.workers.runner.provider_registry import provider_profile_for_key
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# Authentication inputs consumed by the pinned extractors. Other platforms are
# fail-closed until their necessary account Cookie names have been verified.
_ACCOUNT_COOKIES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "instagram": (
        frozenset({"sessionid"}),
        frozenset({"sessionid", "csrftoken", "ds_user_id"}),
    ),
    "qqvideo": (
        frozenset({"v_vuserid", "v_vusession"}),
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
}


class CookieRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    site: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    task_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    deadline: AwareDatetime


class CookieSource:
    def __init__(self, settings: CookieSourceSettings):
        self.settings = settings
        self._password: bytes | None = None
        self._lock = asyncio.Lock()
        self.session_evidence: dict[str, int | bool] | None = None
        self.acl_evidence: dict[str, int | bool] | None = None
        self._disabled = False

    def close(self) -> None:
        # Release references; Python cannot guarantee reliable memory zeroing.
        self._password = None

    def _validate_acl(self, timeout: float = 60) -> None:
        try:
            self.acl_evidence = validate_storage_acl(timeout)
        except KeychainUnavailable:
            self._disabled = True
            self.close()
            raise

    async def start(self) -> None:
        try:
            await asyncio.to_thread(require_unlocked)
            await self._bounded_thread(self._validate_acl)
        except KeychainUnavailable:
            # Locked startup remains unavailable until a later unlocked request;
            # malformed/denied ACL permanently disables this process.
            pass

    async def _bounded_thread[T](self, function: Callable[[], T]) -> T:
        task = asyncio.create_task(asyncio.to_thread(function))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            except Exception:
                pass
            raise

    def _read_password(self, deadline: datetime) -> tuple[bytes, dict[str, int | bool]]:
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise KeychainUnavailable("identity_deadline_invalid")
        self._validate_acl(min(60, remaining))
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise KeychainUnavailable("identity_deadline_invalid")
        return storage_password(min(5, remaining))

    async def cookies(self, request: CookieRequest) -> dict[str, str]:
        remaining = (request.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise KeychainUnavailable("identity_deadline_invalid")
        async with asyncio.timeout(min(120, remaining)):
            async with self._lock:
                # Always query current lock state, even on cache hits.
                await asyncio.to_thread(require_unlocked)
                if self._disabled:
                    raise KeychainUnavailable("keychain_acl_disabled")
                profile = provider_profile_for_key(request.site)
                if not profile.cookie_domain_allowlist or profile.identity == "none":
                    raise KeychainUnavailable("identity_not_declared")
                if request.site not in _ACCOUNT_COOKIES:
                    raise KeychainUnavailable("identity_cookie_rules_unverified")
                if not self.settings.cookie_source_chrome_profile.is_dir():
                    raise KeychainUnavailable("chrome_profile_missing")
                for attempt in range(2):
                    if self._password is None:
                        password, evidence = await self._bounded_thread(
                            partial(self._read_password, request.deadline)
                        )
                        self._password = password
                        self.session_evidence = evidence
                    payload = await self._extract(request)
                    if payload is None:
                        self._password = None
                        if attempt == 0:
                            await asyncio.to_thread(require_unlocked)
                            continue
                        raise KeychainUnavailable("cookie_decryption_failed")
                    lines = parse_cookie_payload(
                        payload, profile.cookie_domain_allowlist
                    )
                    now = datetime.now(UTC).timestamp()
                    if any(line.expires and line.expires <= now for line in lines):
                        raise KeychainUnavailable("cookie_expired")
                    required, necessary = _ACCOUNT_COOKIES[request.site]
                    if not required <= {line.name for line in lines}:
                        raise KeychainUnavailable("site_not_logged_in")
                    # Account values define identity; order, expiry renewal and
                    # changing analytics/visitor Cookies do not change its digest.
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
                    return {
                        "cookies": base64.b64encode(payload).decode("ascii"),
                        "digest": digest,
                    }
        raise KeychainUnavailable("cookie_decryption_failed")

    async def _extract(self, request: CookieRequest) -> bytes | None:
        remaining = (request.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise KeychainUnavailable("identity_deadline_invalid")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.workers.identity.chrome_profile_reader",
            "--profile",
            str(self.settings.cookie_source_chrome_profile),
            "--site",
            request.site,
            cwd=Path(__file__).resolve().parents[3],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            async with asyncio.timeout(min(20, remaining)):
                payload, _ = await process.communicate(self._password)
        finally:
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        if process.returncode == 68:
            return None
        if process.returncode != 0 or len(payload) > MAX_COOKIE_BYTES:
            cause = {
                66: "chrome_profile_missing",
                67: "site_not_logged_in",
                69: "chrome_profile_unreadable",
            }.get(process.returncode or 0, "cookie_read_failed")
            raise KeychainUnavailable(cause)
        return payload


def create_app(settings: CookieSourceSettings) -> FastAPI:
    source = CookieSource(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            await source.start()
            yield
        finally:
            source.close()

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
        actual = request.headers.get("authorization", "").encode()
        if not hmac.compare_digest(actual, expected):
            return JSONResponse(
                {"cause": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if request.url.path != "/cookies" or request.method != "POST":
            return JSONResponse({"cause": "not_found"}, status_code=404)
        # Bound the request before Pydantic parses its body.
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

    @app.post("/cookies")
    async def cookies(request: CookieRequest) -> JSONResponse:
        try:
            result = await source.cookies(request)
        except KeychainUnavailable as error:
            return JSONResponse({"cause": error.cause}, status_code=503)
        except TimeoutError:
            return JSONResponse({"cause": "identity_timeout"}, status_code=503)
        except Exception:
            return JSONResponse({"cause": "cookie_read_failed"}, status_code=503)
        return JSONResponse(result)

    return app
