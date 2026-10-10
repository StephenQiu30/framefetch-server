import asyncio
import sys
from pathlib import Path

import pytest
from app.workers.watermark import execute_process


async def test_cancel_reaps_actual_process_group_before_return(tmp_path: Path):
    marker = tmp_path / "pid"
    cancelled = asyncio.Event()
    code = (
        "import os,time,pathlib; "
        "pathlib.Path(__import__('sys').argv[1]).write_text(str(os.getpid())); "
        "time.sleep(30)"
    )
    task = asyncio.create_task(
        execute_process([sys.executable, "-c", code, str(marker)], cancelled=cancelled)
    )
    for _ in range(100):
        if marker.exists():
            break
        await asyncio.sleep(0.01)
    assert marker.exists()
    cancelled.set()
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(task, timeout=3)
    import os

    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


async def test_nonzero_and_timeout_are_failures():
    with pytest.raises(RuntimeError):
        await execute_process([sys.executable, "-c", "raise SystemExit(2)"])
    with pytest.raises(RuntimeError):
        await execute_process(
            [sys.executable, "-c", "import time;time.sleep(30)"], timeout=0.05
        )


async def test_cancelling_upload_waits_for_storage_before_cleanup():
    from app.workers.watermark import settle_storage

    started, finish = asyncio.Event(), asyncio.Event()
    completed = []

    async def upload():
        started.set()
        await finish.wait()
        completed.append("uploaded")

    task = asyncio.create_task(settle_storage(upload()))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert completed == ["uploaded"]
