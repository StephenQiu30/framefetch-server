"""Run with: python -m app.workers.main.

One process owns every containerized background loop: Outbox dispatch, link
inspection and downloads, imports, report publication.
Each component is supervised on its own, so one failing loop restarts without
stopping the others. The host AI worker and the media Runner stay separate
processes because they hold different credentials and trust boundaries.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import socket
from collections.abc import Iterable
from typing import Protocol

from app.core.config import Settings, get_settings_for_role
from app.core.db import create_engine
from app.workers.download import runtime as download
from app.workers.imports import runtime as imports
from app.workers.outbox import runtime as outbox
from app.workers.report import runtime as report
from app.workers.supervision import install_signal_handlers, run_resilient
from sqlalchemy.ext.asyncio import AsyncEngine

_log = logging.getLogger(__name__)


class WorkerComponent(Protocol):
    async def serve(self, stop: asyncio.Event) -> None: ...

    async def close(self) -> None: ...


def build_components(
    settings: Settings, engine: AsyncEngine
) -> dict[str, WorkerComponent]:
    identity = _process_identity()
    return {
        "outbox": outbox.build_runtime(
            settings, engine, publisher_id=f"outbox-{identity}"
        ),
        "download": download.build_runtime(settings, engine),
        "import": imports.build_runtime(settings, engine),
        "report": report.build_runtime(
            settings, engine, worker_id=f"report-{identity}"
        ),
    }


async def run() -> None:
    settings = get_settings_for_role("worker")
    engine = create_engine(settings.database_url)
    components: dict[str, WorkerComponent] = {}
    try:
        components = build_components(settings, engine)
        stop = asyncio.Event()
        install_signal_handlers(stop)
        async with asyncio.TaskGroup() as tasks:
            for name, component in components.items():
                tasks.create_task(
                    run_resilient(name, component.serve, stop), name=f"worker-{name}"
                )
    finally:
        await asyncio.shield(_close(components.values()))
        await engine.dispose()


async def _close(components: Iterable[WorkerComponent]) -> None:
    for component in components:
        try:
            await component.close()
        except Exception:
            _log.exception("worker component failed to close")


def _process_identity() -> str:
    hostname = socket.gethostname()
    digest = hashlib.sha256(hostname.encode()).hexdigest()[:12]
    return f"{hostname[:64]}-{digest}-{os.getpid()}"


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
