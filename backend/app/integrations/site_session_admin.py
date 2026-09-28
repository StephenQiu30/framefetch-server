"""Administrator access to site sessions: status, remote login and revocation.

Remote login is relayed to the session broker over its admin channel; the API
never sees a Cookie. Frames and keystrokes pass through in memory only.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.integrations.site_session_catalog import (
    site_target,
    site_target_for_host,
    site_target_for_url,
)
from app.repositories.providers.site_sessions import (
    SiteSessionConflict,
    SiteSessionSecrets,
    SiteSessionStates,
)
from app.services.site_sessions import (
    InvalidSessionSite,
    SiteSessionPolicy,
    SiteSessionState,
    SiteSessionStatus,
    known_site_policies,
)
from app.workers.runner.errors import RunnerFailure
from app.workers.session.contracts import (
    ADMIN_LOGIN_CANCEL_PATH,
    ADMIN_LOGIN_FINISH_PATH,
    ADMIN_LOGIN_FRAME_PATH,
    ADMIN_LOGIN_INPUT_PATH,
    ADMIN_LOGIN_START_PATH,
    LoginAction,
    LoginFrame,
    LoginInputRequest,
    LoginRef,
    LoginSaved,
    LoginStarted,
    LoginStartRequest,
)
from app.workers.session.rpc import RpcError, SignedClient
from app.workers.session.sealing import decode

# A page load inside the login browser may take up to its 60 s budget.
_TIMEOUT_SECONDS = 75


class SiteSessionAdminError(Exception):
    """``code`` is one of the stable reasons below, safe to map for users."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class SiteSessionView:
    site: str
    provider_key: str | None
    state: SiteSessionState | None
    seed_revision: int | None
    verified_at: datetime | None
    refreshed_at: datetime | None
    last_error_code: str | None
    proves_login: bool


@dataclass(frozen=True, slots=True)
class LoginView:
    login_id: str
    site: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class FrameView:
    jpeg: bytes
    host: str
    logged_in: bool


class SiteSessionAdmin:
    def __init__(
        self,
        *,
        states: SiteSessionStates,
        secrets: SiteSessionSecrets,
        broker_url: str,
        admin_secret: bytes,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._states, self._secrets = states, secrets
        self._http = client or httpx.AsyncClient(
            base_url=broker_url, timeout=_TIMEOUT_SECONDS
        )
        self._broker = SignedClient(self._http, admin_secret)

    async def list(self) -> tuple[SiteSessionView, ...]:
        """Every known platform, plus every site with a stored record."""
        stored = {status.site: status for status in await self._states.list()}
        views = [
            _view(policy, stored.pop(policy.site, None))
            for policy in known_site_policies()
        ]
        views += [
            _view(site_target(site).policy, status)
            for site, status in sorted(stored.items())
        ]
        return tuple(views)

    async def start(self, target: str) -> LoginView:
        """Start a login for a known site key, a host or any page URL."""
        site, url = _resolve(target)
        started = await self._call(
            ADMIN_LOGIN_START_PATH, LoginStartRequest(site=site, url=url), LoginStarted
        )
        return LoginView(started.login_id, started.site, started.width, started.height)

    async def frame(self, login_id: str) -> FrameView:
        frame = await self._call(ADMIN_LOGIN_FRAME_PATH, _ref(login_id), LoginFrame)
        return FrameView(decode(frame.image), frame.host, frame.logged_in)

    async def act(self, login_id: str, actions: Sequence[dict[str, Any]]) -> None:
        try:
            body = LoginInputRequest(
                login_id=login_id,
                actions=tuple(LoginAction.model_validate(item) for item in actions),
            )
        except ValidationError:
            raise SiteSessionAdminError("site_session_invalid") from None
        await self._call(ADMIN_LOGIN_INPUT_PATH, body, None)

    async def finish(self, login_id: str) -> tuple[str, int]:
        saved = await self._call(ADMIN_LOGIN_FINISH_PATH, _ref(login_id), LoginSaved)
        return saved.site, saved.seed_revision

    async def cancel(self, login_id: str) -> None:
        await self._call(ADMIN_LOGIN_CANCEL_PATH, _ref(login_id), None)

    async def revoke(self, site: str) -> None:
        status = await self._states.get(site)
        if status is None or status.state is SiteSessionState.REVOKED:
            raise SiteSessionAdminError("site_session_not_found")
        try:
            await self._secrets.revoke(
                site, expected_seed_revision=status.seed_revision
            )
        except SiteSessionConflict:
            raise SiteSessionAdminError("site_session_login_busy") from None

    async def close(self) -> None:
        await self._http.aclose()

    async def _call[T: BaseModel](
        self, path: str, body: BaseModel, response: type[T] | None
    ) -> T:
        try:
            if response is None:
                await self._broker.post_empty(path, body)
                return None  # type: ignore[return-value]
            return await self._broker.post(path, body, response)
        except RpcError as exc:
            raise SiteSessionAdminError(
                _CODES.get(exc.code, "site_session_unavailable")
            ) from exc


_CODES = {
    "login_busy": "site_session_login_busy",
    "login_not_found": "site_session_login_not_found",
    "login_incomplete": "site_session_login_incomplete",
    "login_not_accepted": "site_session_login_rejected",
    "login_url_invalid": "site_session_invalid",
    "invalid_request": "site_session_invalid",
}


def _ref(login_id: str) -> LoginRef:
    try:
        return LoginRef(login_id=login_id)
    except ValidationError:
        raise SiteSessionAdminError("site_session_login_not_found") from None


def _resolve(target: str) -> tuple[str, str | None]:
    value = target.strip()
    try:
        if "://" in value:
            return site_target_for_url(value).site, value
        return site_target_for_host(value).site, None
    except (InvalidSessionSite, RunnerFailure):
        raise SiteSessionAdminError("site_session_invalid") from None


def _view(
    policy: SiteSessionPolicy, status: SiteSessionStatus | None
) -> SiteSessionView:
    return SiteSessionView(
        site=policy.site,
        provider_key=None if policy.provider_key is None else policy.provider_key.value,
        state=None if status is None else status.state,
        seed_revision=None if status is None else status.seed_revision,
        verified_at=None if status is None else status.verified_at,
        refreshed_at=None if status is None else status.refreshed_at,
        last_error_code=None if status is None else status.last_error_code,
        proves_login=policy.login_probe.proves_login
        or policy.header_plugin is not None,
    )


def jpeg_base64(frame: FrameView) -> str:
    return base64.b64encode(frame.jpeg).decode("ascii")
