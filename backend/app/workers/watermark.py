"""Single-concurrency RabbitMQ video processing worker with an isolated runtime.

Run as the host user for MPS; the same entry point supports a CUDA worker host.
No platform credentials or media URLs are passed to the processing process.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import tempfile
from collections.abc import Coroutine
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import aio_pika
from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.integrations.messaging.envelope import EventEnvelope
from app.integrations.messaging.topology import RabbitMqTopology, declare_durable_queue
from app.integrations.object_storage import MinioObjectStorage
from app.repositories.watermark import MAX_OUTPUT_BYTES, WatermarkRepository


async def execute_process(
    command: list[str], *, timeout: float = 1800, cancelled: asyncio.Event | None = None
) -> None:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    waiting = asyncio.create_task(process.wait())
    stopping = asyncio.create_task(cancelled.wait()) if cancelled else None
    try:
        done, _ = await asyncio.wait(
            {waiting, stopping} if stopping else {waiting},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if waiting not in done or waiting.result() != 0:
            raise RuntimeError("processing failed, timed out or cancelled")
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
        for task in (waiting, stopping):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(t for t in (waiting, stopping) if t is not None), return_exceptions=True
        )


async def settle_storage[T](operation: Coroutine[Any, Any, T]) -> T:
    """Thread-backed storage must finish before cleanup can remove its key/file."""
    pending = asyncio.create_task(operation)
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        # MinIO runs in a thread: cancelling the await does not stop a PUT.
        # Keep the lease heartbeat alive until that PUT has actually stopped.
        with suppress(Exception):
            await pending
        raise


async def execute(
    task_id: UUID,
    worker: str,
    repo: WatermarkRepository,
    storage: MinioObjectStorage,
    command: list[str],
) -> None:
    claimed = await repo.claim(task_id, worker)
    if claimed is None:
        return
    task, source = claimed
    assert task.object_key
    cancelled = asyncio.Event()
    published = False

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(20)
            try:
                alive = await repo.heartbeat_task(task.id, worker, task.attempt)
            except Exception:
                alive = False
            if not alive:
                cancelled.set()
                return

    pulse = asyncio.create_task(heartbeat())
    try:
        with tempfile.TemporaryDirectory(prefix="framefetch-watermark-") as directory:
            root = Path(directory)
            if shutil.disk_usage(root).free < MAX_OUTPUT_BYTES * 3:
                raise RuntimeError("insufficient scratch space")
            incoming, output = root / "source.mp4", root / "video.mp4"
            await settle_storage(storage.download(source.object_key, incoming))
            if incoming.stat().st_size != source.size_bytes or cancelled.is_set():
                raise RuntimeError("source unavailable")
            manifest = root / "task.json"
            manifest.write_text(
                json.dumps(
                    {
                        "source": str(incoming),
                        "output": str(output),
                        "sha256": source.sha256,
                    }
                )
            )
            await execute_process(
                [*command, "--manifest", str(manifest)], cancelled=cancelled
            )
            evidence = json.loads(output.with_suffix(".json").read_text())
            if cancelled.is_set() or not await repo.heartbeat_task(
                task.id, worker, task.attempt
            ):
                raise RuntimeError("lease lost")
            if evidence["source_sha256"] != source.sha256:
                raise RuntimeError("output validation failed")
            if evidence.get("error_code") == "unsupported_media":
                await repo.finish(
                    task.id, worker, task.attempt, error="unsupported_media"
                )
                return
            if evidence.get("unchanged"):
                published = await repo.finish(
                    task.id, worker, task.attempt, unchanged=True
                )
                return
            if not 0 < output.stat().st_size <= MAX_OUTPUT_BYTES:
                raise RuntimeError("output validation failed")
            await settle_storage(
                storage.upload_verified(
                    output,
                    task.object_key,
                    expected_size_bytes=evidence["size_bytes"],
                    sha256=evidence["sha256"],
                    content_type="video/mp4",
                )
            )
            published = await repo.finish(
                task.id,
                worker,
                task.attempt,
                size=evidence["size_bytes"],
                sha256=evidence["sha256"],
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        await repo.finish(task.id, worker, task.attempt, error="processing_failed")
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
        if not published:
            # Keep the planned key in the row until original deletion; failed
            # cleanup can always be retried and is never an untracked object.
            with suppress(Exception):
                await storage.delete(task.object_key)
                await repo.cleaned(task.object_key)
        await repo.release(task.id, worker, task.attempt)


async def serve(args: argparse.Namespace) -> None:
    command = [
        str(args.python.absolute()),
        str(Path(__file__).resolve().parents[2] / "scripts/process_watermark.py"),
        "--vsr-root",
        str(args.vsr_root.resolve()),
        "--model",
        str(args.model.resolve()),
        "--device",
        args.device,
        "--detector",
        str(args.detector.resolve()),
    ]
    await execute_process(command, timeout=120)
    settings = Settings()
    engine = create_engine(settings.database_url)
    repo = WatermarkRepository(create_session_factory(engine))
    storage = MinioObjectStorage(settings)
    worker = f"watermark-{uuid4()}"
    topology = RabbitMqTopology()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    async def maintain() -> None:
        while not stop.is_set():
            await repo.heartbeat_worker(worker)
            for key in await repo.recover():
                with suppress(Exception):
                    await storage.delete(key)
                    await repo.cleaned(key)
            try:
                await asyncio.wait_for(stop.wait(), timeout=30)
            except TimeoutError:
                pass

    maintenance = asyncio.create_task(maintain())
    try:
        async with await aio_pika.connect_robust(
            settings.rabbitmq_url, heartbeat=60, timeout=10
        ) as connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=1)
            queue = await declare_durable_queue(channel, topology, topology.watermark)
            # Sequential iterator gives one execution owner per worker process.
            async with queue.iterator() as messages:

                async def consume() -> None:
                    async for message in messages:
                        try:
                            event = EventEnvelope.from_bytes(message.body)
                            if (
                                event.event_type != "watermark.requested"
                                or event.payload != {"task_id": str(event.aggregate_id)}
                            ):
                                raise ValueError("invalid command")
                        except ValueError:
                            await message.reject(requeue=False)
                            continue
                        try:
                            await execute(
                                event.aggregate_id, worker, repo, storage, command
                            )
                            await message.ack()
                        except asyncio.CancelledError:
                            with suppress(Exception):
                                await message.nack(requeue=True)
                            raise
                        except Exception:
                            await message.nack(requeue=not bool(message.redelivered))

                consumer = asyncio.create_task(consume())
                stopping = asyncio.create_task(stop.wait())
                try:
                    await asyncio.wait(
                        {consumer, stopping, maintenance},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    consumer.cancel()
                    stopping.cancel()
                    await asyncio.gather(consumer, stopping, return_exceptions=True)
    finally:
        maintenance.cancel()
        await asyncio.gather(maintenance, return_exceptions=True)
        await repo.offline(worker)
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--vsr-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "mps", "cuda"], required=True)
    asyncio.run(serve(parser.parse_args()))


if __name__ == "__main__":
    main()
