"""Process lifecycle shared by the worker process and the host AI worker."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable

_log = logging.getLogger(__name__)

Component = Callable[[asyncio.Event], Awaitable[None]]


def install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for requested_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(requested_signal, stop.set)
        except NotImplementedError:
            pass


async def run_resilient(
    name: str,
    component: Component,
    stop: asyncio.Event,
    *,
    initial_delay: float = 1.0,
) -> None:
    """Keep one component running until stop; a failure restarts only it."""
    delay = initial_delay
    while not stop.is_set():
        try:
            await component(stop)
            if stop.is_set():
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("worker component %s failed; restarting", name)
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            delay = min(delay * 2, 30.0)
