"""Shared IP/owner admission for explicitly annotated API operations."""

from ipaddress import ip_address, ip_network
from typing import Annotated, cast

from fastapi import Depends, Request

from app.api.deps import get_current_user, get_runtime_settings
from app.core.config import RateLimitOperation, Settings
from app.core.errors import AppError
from app.integrations.rate_limiter import (
    RateLimiterUnavailable,
    RateLimitExceeded,
    RedisRateLimiter,
)
from app.services.auth.models import CurrentUser


class RateLimitAdmission:
    def __init__(self, operation: RateLimitOperation) -> None:
        self.operation = operation

    async def __call__(
        self,
        request: Request,
        user: Annotated[CurrentUser, Depends(get_current_user)],
        settings: Annotated[Settings, Depends(get_runtime_settings)],
    ) -> None:
        if user.is_admin:
            return
        await enforce_rate_limit(request, self.operation, user.owner_hash, settings)


async def enforce_rate_limit(
    request: Request,
    operation: RateLimitOperation,
    owner_hash: str,
    settings: Settings,
    *,
    include_client_ip: bool = False,
) -> None:
    limiter = cast(
        RedisRateLimiter | None,
        getattr(request.app.state.services, "rate_limiter", None),
    )
    if limiter is None:
        return
    client_host = None
    if include_client_ip:
        trusted = settings.trusted_proxy_cidrs + tuple(
            str(address) for address in settings.trusted_web_proxy_ips
        )
        client_host = _client_host(request, trusted)
    try:
        await limiter.check(
            operation=operation,
            owner_hash=owner_hash,
            client_host=client_host,
        )
    except RateLimitExceeded as exc:
        raise AppError(
            status=429,
            code="operation_rate_limited",
            title="Too many requests",
            detail="The operation rate limit has been exceeded.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except RateLimiterUnavailable as exc:
        raise AppError(
            status=503,
            code="rate_limiter_unavailable",
            title="Service unavailable",
            detail="The operation admission service is unavailable.",
        ) from exc


def _client_host(request: Request, trusted_proxy_cidrs: tuple[str, ...]) -> str:
    peer_host = request.client.host if request.client else "unknown"
    try:
        peer = ip_address(peer_host)
    except ValueError:
        return peer_host
    trusted = tuple(ip_network(cidr) for cidr in trusted_proxy_cidrs)
    if not any(peer in network for network in trusted):
        return peer.compressed
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer.compressed
    candidates = [candidate.strip() for candidate in forwarded.split(",")]
    if not candidates or any(not candidate for candidate in candidates):
        return peer.compressed
    for candidate in reversed(candidates):
        try:
            address = ip_address(candidate)
        except ValueError:
            return peer.compressed
        if not any(address in network for network in trusted):
            return address.compressed
    return peer.compressed
