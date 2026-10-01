"""L2 proof: declared YouTube clients and bounded first-party guest requests."""

import json
import logging
import re
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from app.services.provider_failures import (
    FailureClass,
    ProviderFailure,
    parse_retry_after,
)
from app.workers.runner.engine import identity
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.engine.layers.http import HttpLayer
from app.workers.runner.engine.resolved import ResolvedMedia
from app.workers.runner.engine.run_context import ResolutionSource, RunContext
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.netscape_cookie import (
    has_safe_cookie_fields,
    is_allowed_domain,
    serialize_cookies,
)

_LOG = logging.getLogger(__name__)

_CLIENT_FALLBACK = {
    FailureClass.CONTENT_PROTECTED,
    FailureClass.FORMAT_UNAVAILABLE,
    FailureClass.EXTRACTOR_BROKEN,
    FailureClass.CHALLENGE,
    FailureClass.NETWORK_BLOCKED,
}
_MAX_RESPONSE_BYTES = 1024 * 1024
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_GUEST_DOMAINS = {
    "kuaishou": frozenset({"kuaishou.com"}),
    "weibo": frozenset({"weibo.com"}),
}


def _failure(kind: FailureClass, cause: str) -> LayerFailure:
    return LayerFailure(kind, "②", {"kind": "upstream_response", "cause_code": cause})


class PreparedLayer:
    def __init__(self) -> None:
        self.failures: list[ProviderFailure] = []

    async def resolve(self, source: ResolutionSource, ctx: RunContext) -> ResolvedMedia:
        self.failures.clear()
        spec = source.request.profile.l2_prepare
        if spec is None:
            raise _failure(FailureClass.RUNTIME_UNAVAILABLE, "preparation_not_declared")
        if spec.kind == "po_token" and source.request.profile.key == "youtube":
            return await self._youtube(source, ctx, spec.clients)
        if spec.kind == "visitor" and source.request.profile.key in _GUEST_DOMAINS:
            prepared = await prepare_visitor(source.request.profile.key, ctx)
            try:
                media = await HttpLayer().resolve(source, prepared)
                return replace(media, run_context=prepared)
            except BaseException:
                # No successful Resolution will own this material on failure.
                if (
                    prepared.cookie_file is not None
                    and prepared.cookie_file != ctx.cookie_file
                ):
                    prepared.cookie_file.unlink(missing_ok=True)
                    prepared.cookie_file.parent.rmdir()
                raise
        raise _failure(FailureClass.RUNTIME_UNAVAILABLE, "preparation_not_supported")

    async def _youtube(
        self, source: ResolutionSource, ctx: RunContext, clients: tuple[str, ...]
    ) -> ResolvedMedia:
        if source.expected_context is not None:
            selected = source.expected_context.client.removeprefix("youtube:")
            if selected not in clients:
                raise RunnerFailure("context_changed", status=409)
            clients = (selected,)
        errors: list[RunnerFailure] = []
        for client in clients:
            context = replace(source.execution_context, client=f"youtube:{client}")
            try:
                return await HttpLayer().resolve(
                    replace(source, execution_context=context), ctx
                )
            except RunnerFailure as error:
                error.attributed_to(context)
                _LOG.info(
                    "proof client failed task=%s provider=youtube layer=L2 "
                    "client=%s class=%s gate=%s evidence=%s",
                    source.workspace.path.name.rsplit("-", 1)[0],
                    context.client,
                    error.failure.failure_class,
                    error.failure.gate,
                    error.failure.evidence,
                )
                errors.append(error)
                self.failures.append(error.failure)
                if (
                    source.expected_context is not None
                    or error.failure.failure_class not in _CLIENT_FALLBACK
                ):
                    error.failures = tuple(self.failures)
                    raise
        if not errors:
            raise _failure(FailureClass.RUNTIME_UNAVAILABLE, "clients_not_declared")
        if all(
            error.failure.failure_class is FailureClass.CONTENT_PROTECTED
            for error in errors
        ):
            final = errors[-1]
        else:
            # DRM/SABR is a client result. A bot wall/failed proof is stronger
            # evidence than a different client's empty or protected format list.
            final = min(
                (
                    error
                    for error in errors
                    if error.failure.failure_class is not FailureClass.CONTENT_PROTECTED
                ),
                key=lambda error: {
                    FailureClass.CHALLENGE: 0,
                    FailureClass.NETWORK_BLOCKED: 1,
                    FailureClass.EXTRACTOR_BROKEN: 2,
                    FailureClass.FORMAT_UNAVAILABLE: 3,
                }[error.failure.failure_class],
            )
        final.failures = tuple(self.failures)
        raise final


async def _request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    domains: frozenset[str],
    **kwargs: object,
) -> bytes:
    # Fixed first-party URLs only; redirects cannot escape the preparation scope.
    for _ in range(4):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or not is_allowed_domain(parsed.hostname or "", domains)
        ):
            raise _failure(FailureClass.INVALID_INPUT, "visitor_redirect_denied")
        async with client.stream(method, url, **kwargs) as response:  # type: ignore[arg-type]
            if response.status_code == 429:
                raise LayerFailure(
                    FailureClass.RATE_LIMITED,
                    "①",
                    {"kind": "upstream_response", "http_status": 429},
                    parse_retry_after(
                        response.headers.get("Retry-After"), datetime.now(UTC)
                    ),
                )
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise _failure(
                        FailureClass.EXTRACTOR_BROKEN, "visitor_redirect_invalid"
                    )
                url = urljoin(url, location)
                method, kwargs = "GET", {}
                continue
            if response.status_code >= 500:
                raise _failure(FailureClass.TRANSIENT, "visitor_upstream_unavailable")
            if response.status_code in {401, 403, 412}:
                raise _failure(FailureClass.CHALLENGE, "visitor_challenged")
            if response.status_code != 200:
                raise _failure(
                    FailureClass.EXTRACTOR_BROKEN, "visitor_response_invalid"
                )
            result = bytearray()
            async for chunk in response.aiter_bytes():
                result.extend(chunk)
                if len(result) > _MAX_RESPONSE_BYTES:
                    raise _failure(
                        FailureClass.EXTRACTOR_BROKEN, "visitor_response_too_large"
                    )
            return bytes(result)
    raise _failure(FailureClass.EXTRACTOR_BROKEN, "visitor_redirect_limit")


async def prepare_visitor(site: str, ctx: RunContext) -> RunContext:
    domains = _GUEST_DOMAINS[site]
    ua = ctx.user_agent or _USER_AGENT
    referer = f"https://www.{site}.com/" if site == "kuaishou" else "https://weibo.com/"
    try:
        async with httpx.AsyncClient(
            proxy=ctx.egress.proxy_url,
            trust_env=False,
            follow_redirects=False,
            timeout=min(
                10.0, max(0.001, (ctx.deadline - datetime.now(UTC)).total_seconds())
            ),
            headers={"User-Agent": ua, "Referer": referer},
        ) as client:
            if ctx.cookie_file is not None:
                existing = MozillaCookieJar(str(ctx.cookie_file))
                existing.load(ignore_discard=True)
                client.cookies = httpx.Cookies(existing)
            # Kuaishou: GET https://www.kuaishou.com/ -> first-visit Cookie -> yt-dlp.
            # Weibo: homepage -> passport genvisitor POST -> visitor incarnate GET
            # -> homepage -> yt-dlp. Parameters mirror upstream WeiboBaseIE;
            # no local signatures, JS emulation or login credentials are generated.
            await _request(client, "GET", referer, domains)
            if site == "weibo":
                raw = await _request(
                    client,
                    "POST",
                    "https://passport.weibo.com/visitor/genvisitor",
                    domains,
                    data={
                        "cb": "gen_callback",
                        "fp": json.dumps(
                            {
                                "os": "1",
                                "browser": "Chrome131,0,0,0",
                                "fonts": "undefined",
                                "screenInfo": "1920*1080*24",
                                "plugins": "",
                            },
                            separators=(",", ":"),
                        ),
                    },
                )
                try:
                    text = raw.decode()
                    match = re.fullmatch(r"\s*gen_callback\((.*)\);?\s*", text, re.S)
                    payload = json.loads(match[1] if match else text)
                    visitor = payload["data"]
                    tid = visitor["tid"]
                    confidence = int(visitor.get("confidence", 100))
                    if (
                        not isinstance(tid, str)
                        or not 0 < len(tid) <= 256
                        or not 0 <= confidence <= 100
                    ):
                        raise ValueError("invalid visitor")
                except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                    raise _failure(
                        FailureClass.EXTRACTOR_BROKEN, "visitor_structure_changed"
                    ) from exc
                await _request(
                    client,
                    "GET",
                    "https://passport.weibo.com/visitor/visitor",
                    domains,
                    params={
                        "a": "incarnate",
                        "t": tid,
                        "w": 3 if visitor.get("new_tid") else 2,
                        "c": f"{confidence:03d}",
                        "gc": "",
                        "cb": "cross_domain",
                        "from": "weibo",
                    },
                )
                await _request(client, "GET", referer, domains)
            cookies = [
                cookie
                for cookie in client.cookies.jar
                if not cookie.is_expired()
                and is_allowed_domain(cookie.domain, domains)
                and has_safe_cookie_fields(cookie)
            ]
            if not cookies:
                raise _failure(FailureClass.CHALLENGE, "visitor_cookie_missing")
            payload_bytes = serialize_cookies(cookies)
    except httpx.HTTPError as exc:
        raise _failure(FailureClass.TRANSIENT, "visitor_transport_failed") from exc
    path = ctx.cookie_file
    operation: Path | None = None
    try:
        if path is None:
            identity.COOKIE_TMPFS_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
            operation = Path(
                tempfile.mkdtemp(prefix="visitor-", dir=identity.COOKIE_TMPFS_ROOT)
            )
            path = operation / "cookies.txt"
            path.touch(mode=0o600)
        identity.validate_cookie_file(path)
        path.write_bytes(payload_bytes)
        return ctx.with_material(cookie_file=path, user_agent=ua, referer=referer)
    except BaseException:
        if operation is not None:
            if path is not None:
                path.unlink(missing_ok=True)
            operation.rmdir()
        raise
