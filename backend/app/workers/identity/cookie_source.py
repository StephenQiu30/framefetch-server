"""Loopback-only, authenticated host Cookie service. No account material is logged."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import CookieSourceSettings
from app.workers.identity.keychain import (
    KeychainUnavailable,
    launchd_storage_password,
    require_unlocked,
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

    async def cookies(self, request: CookieRequest) -> dict[str, str]:
        remaining = (request.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise KeychainUnavailable("identity_deadline_invalid")
        async with asyncio.timeout(min(30, remaining)):
            async with self._lock:
                # Always query current lock state, even on cache hits.
                await asyncio.to_thread(require_unlocked)
                profile = provider_profile_for_key(request.site)
                if not profile.cookie_domain_allowlist or profile.identity == "none":
                    raise KeychainUnavailable("identity_not_declared")
                if request.site not in _ACCOUNT_COOKIES:
                    raise KeychainUnavailable("identity_cookie_rules_unverified")
                if not self.settings.cookie_source_chrome_profile.is_dir():
                    raise KeychainUnavailable("chrome_profile_missing")
                for attempt in range(2):
                    if self._password is None:
                        remaining = (
                            request.deadline - datetime.now(UTC)
                        ).total_seconds()
                        read = asyncio.create_task(
                            asyncio.to_thread(
                                launchd_storage_password, min(10, remaining)
                            )
                        )
                        try:
                            (
                                self._password,
                                self.session_evidence,
                            ) = await asyncio.shield(read)
                        except asyncio.CancelledError:
                            # The bounded thread owns launchctl/socket cleanup.
                            # Do not report cancellation before it has finished.
                            try:
                                await read
                            except Exception:
                                pass
                            raise
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
            cause = {66: "chrome_profile_missing", 67: "site_not_logged_in"}.get(
                process.returncode or 0, "cookie_read_failed"
            )
            raise KeychainUnavailable(cause)
        return payload


def create_app(settings: CookieSourceSettings) -> FastAPI:
    source = CookieSource(settings)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
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
