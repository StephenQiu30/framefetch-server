import asyncio

import pytest
from app.workers.runner.main import _until_disconnect
from fastapi import HTTPException


async def test_disconnected_inspection_waits_for_operation_cleanup():
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    class Request:
        async def receive(self):
            await entered.wait()
            return {"type": "http.disconnect"}

    async def inspect():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    with pytest.raises(HTTPException) as failure:
        await asyncio.wait_for(_until_disconnect(Request(), inspect()), 1)
    assert failure.value.status_code == 499 and cleaned.is_set()
